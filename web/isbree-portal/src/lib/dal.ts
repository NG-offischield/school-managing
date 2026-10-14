import "server-only";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { clientIp } from "./client-ip";
import { djangoHeaders, djangoUrl } from "./django";
import { type Session, SESSION_COOKIE, unsealSession } from "./session";

/**
 * Data Access Layer: every read of personal data goes through here. The
 * session is read from the encrypted cookie (refreshed upstream by
 * proxy.ts) and each call carries the user's own token: Django decides what
 * this user may see, the portal never widens it.
 */
export const currentSession = cache(async (): Promise<Session | null> => {
  const store = await cookies();
  return unsealSession(store.get(SESSION_COOKIE)?.value);
});

export async function requireSession(): Promise<Session> {
  const session = await currentSession();
  if (!session) redirect("/connexion");
  return session;
}

export async function visitorIp() {
  return clientIp((await headers()).get("x-forwarded-for"));
}

export type Loaded<T> = { ok: true; data: T } | { ok: false; status: number };

/** GET a Django API path as the current user. An invalid session goes back to the login page. */
export async function api<T>(path: string, query: Record<string, string | undefined> = {}): Promise<Loaded<T>> {
  const session = await requireSession();
  const url = new URL(djangoUrl(path));
  for (const [name, value] of Object.entries(query)) if (value) url.searchParams.set(name, value);
  let response: Response;
  try {
    response = await fetch(url, {
      headers: djangoHeaders({ token: session.access, clientIp: await visitorIp() }),
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
  } catch {
    return { ok: false, status: 503 };
  }
  if (response.status === 401) redirect("/connexion?session=expiree");
  if (!response.ok) return { ok: false, status: response.status };
  const body = (await response.json()) as { data: T };
  return { ok: true, data: body.data };
}
