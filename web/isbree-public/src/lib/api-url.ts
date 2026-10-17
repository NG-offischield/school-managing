/**
 * Normalises DJANGO_INTERNAL_API_URL into the API's versioned base.
 *
 * Every API path of this app is relative to `/api/v1` (e.g. `public/ISBREE/site/`).
 * A value given without it ("https://isbree-api.onrender.com"), without a
 * scheme or with a trailing slash used to send every call to a 404 page,
 * which the pages could only show as "temporarily unavailable". Accepted:
 *   https://host            -> https://host/api/v1
 *   https://host/           -> https://host/api/v1
 *   https://host/api/v1/    -> https://host/api/v1
 *   host.example.com/api/v1 -> https://host.example.com/api/v1
 * A different explicit version (/api/v2) is kept as is.
 */
export const DEFAULT_API_URL = "http://localhost:8000/api/v1";

export function normalizeApiUrl(raw: string | undefined | null) {
  let value = (raw || "").trim();
  if (!value) return DEFAULT_API_URL;
  if (!/^https?:\/\//i.test(value)) value = `https://${value}`;
  value = value.replace(/\/+$/, "");
  if (!/\/api\/v\d+$/i.test(value)) value = `${value}/api/v1`;
  return value;
}

/** Same rule for the public addresses of the two sites (no path added). */
export function normalizeSiteUrl(raw: string | undefined | null, fallback: string) {
  let value = (raw || "").trim();
  if (!value) return fallback;
  if (!/^https?:\/\//i.test(value)) value = `https://${value}`;
  return value.replace(/\/+$/, "");
}

/**
 * One line in the server log (Render "Logs") for every failed API call:
 * method, API path (no query string, no body, no header) and the HTTP status
 * or the network error's name. Never a token, a password or personal data.
 */
export function logApiFailure(method: string, url: string, outcome: number | unknown) {
  let path = url;
  try {
    const parsed = new URL(url);
    path = `${parsed.origin}${parsed.pathname}`;
  } catch {
    // keep the raw value: it is our own configuration, not user input
  }
  const what =
    typeof outcome === "number" ? `HTTP ${outcome}` : `network error ${(outcome as Error)?.name ?? "unknown"}`;
  console.error(`[isbree] API ${method} ${path} -> ${what}`);
}
