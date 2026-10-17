import { logApiFailure } from "./api-url";
import { config } from "./config";
import { type Session, sessionFromTokens, type TokenPayload } from "./session";

/**
 * Server-to-server calls to Django. Used by proxy.ts, server actions, route
 * handlers and the data access layer. The browser never calls Django and
 * never sees a token.
 */
export function djangoHeaders({ token, clientIp, json }: { token?: string; clientIp?: string; json?: boolean } = {}) {
  const headers: Record<string, string> = { Accept: "application/json", "X-School-Code": config.schoolCode };
  if (json) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  if (config.bffToken) {
    headers["X-ISBREE-BFF"] = config.bffToken;
    if (clientIp) headers["X-ISBREE-Client-IP"] = clientIp;
  }
  return headers;
}

export function djangoUrl(path: string) {
  return `${config.apiUrl}/${path.replace(/^\/+/, "")}`;
}

export type ApiResult<T> = { ok: true; status: number; data: T } | { ok: false; status: number; error: ApiError | null };
export type ApiError = { code?: string; message?: string; details?: Record<string, unknown> };

/** No HTTP answer at all (timeout, refused connection): the API is asleep or unreachable. */
export const NO_RESPONSE = 0;

export async function postJson<T>(path: string, body: unknown, opts: { token?: string; clientIp?: string } = {}): Promise<ApiResult<T>> {
  const url = djangoUrl(path);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: djangoHeaders({ ...opts, json: true }),
      body: JSON.stringify(body),
      cache: "no-store",
      // A free API host can take up to about a minute to wake up.
      signal: AbortSignal.timeout(75000),
    });
    const parsed = (await response.json().catch(() => null)) as { data?: T; error?: ApiError } | null;
    if (response.ok) return { ok: true, status: response.status, data: parsed?.data as T };
    // 400 / 401 / 403 / 429 are expected answers (wrong password, throttling): not logged.
    if (response.status === 404 || response.status >= 500) logApiFailure("POST", url, response.status);
    return { ok: false, status: response.status, error: parsed?.error ?? null };
  } catch (error) {
    logApiFailure("POST", url, error);
    return { ok: false, status: NO_RESPONSE, error: null };
  }
}

/*
 * Refresh de-duplication. Django rotates the refresh token and treats the
 * reuse of an old one as a theft (the whole session is revoked). Parallel
 * requests of the same browser (page + prefetches + downloads) must therefore
 * share ONE refresh: the in-flight promise, then its result for 30 s, are
 * kept per session id. (Per process: one Next.js instance per portal, see
 * docs/isbree-web.md.)
 */
const inFlight = new Map<string, Promise<Session | null>>();
const recent = new Map<string, { session: Session; at: number }>();

export async function refreshSession(session: Session, clientIp?: string): Promise<Session | null> {
  const done = recent.get(session.sessionId);
  if (done && Date.now() - done.at < 30_000) return done.session;
  const pending = inFlight.get(session.sessionId);
  if (pending) return pending;
  const promise = (async () => {
    const result = await postJson<TokenPayload>("auth/refresh/", { refresh_token: session.refresh }, { clientIp });
    if (!result.ok) return null;
    const next = sessionFromTokens(result.data);
    recent.set(session.sessionId, { session: next, at: Date.now() });
    return next;
  })();
  inFlight.set(session.sessionId, promise);
  try {
    return await promise;
  } finally {
    inFlight.delete(session.sessionId);
    for (const [id, entry] of recent) if (Date.now() - entry.at > 60_000) recent.delete(id);
  }
}
