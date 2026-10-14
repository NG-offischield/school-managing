import { type NextRequest, NextResponse } from "next/server";

import { clientIp } from "./lib/client-ip";
import { refreshSession } from "./lib/django";
import { needsRefresh, SESSION_COOKIE, sealSession, sessionCookieOptions, unsealSession } from "./lib/session";

/**
 * Runs before every page and route of the portal:
 *  - optimistic access check: no valid session cookie -> login page (the real
 *    check is Django's, on every API call);
 *  - token refresh: an access token about to expire is renewed ONCE here
 *    (de-duplicated), and the new cookie is passed both to the page being
 *    rendered and to the browser;
 *  - nothing personal is ever cached: "private, no-store" on every response.
 */
const PUBLIC_PATHS = ["/connexion", "/activation"];

function isPublic(pathname: string) {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

function noStore(response: NextResponse) {
  response.headers.set("Cache-Control", "private, no-store, max-age=0");
  return response;
}

function toLogin(request: NextRequest, reason?: string) {
  const url = new URL("/connexion", request.url);
  if (reason) url.searchParams.set("session", reason);
  const response = NextResponse.redirect(url);
  response.cookies.delete(SESSION_COOKIE);
  return noStore(response);
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const raw = request.cookies.get(SESSION_COOKIE)?.value;
  let session = await unsealSession(raw);

  if (!session) {
    if (isPublic(pathname)) {
      const response = NextResponse.next();
      if (raw) response.cookies.delete(SESSION_COOKIE); // unreadable or expired cookie
      return noStore(response);
    }
    return toLogin(request, raw ? "expiree" : undefined);
  }

  if (needsRefresh(session)) {
    const renewed = await refreshSession(session, clientIp(request.headers.get("x-forwarded-for")));
    if (!renewed) {
      if (isPublic(pathname)) {
        const response = NextResponse.next();
        response.cookies.delete(SESSION_COOKIE);
        return noStore(response);
      }
      return toLogin(request, "expiree");
    }
    session = renewed;
    const sealed = await sealSession(session);
    request.cookies.set(SESSION_COOKIE, sealed); // seen by the page rendered for this request
    const response = NextResponse.next({ request: { headers: request.headers } });
    response.cookies.set(SESSION_COOKIE, sealed, sessionCookieOptions(session)); // kept by the browser
    return noStore(response);
  }

  return noStore(NextResponse.next());
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|icon.svg|robots.txt).*)"],
};
