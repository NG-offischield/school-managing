import { EncryptJWT, jwtDecrypt } from "jose";

import { config } from "./config";

/**
 * The portal session (BFF, ADR 0032): Django's access and refresh tokens are
 * kept in ONE encrypted (A256GCM), HttpOnly, SameSite=Lax cookie. JavaScript
 * in the page cannot read it, and nothing is ever written to localStorage.
 * The cookie lives as long as the Django refresh token; Django stays the
 * authority (revocation, expiry, roles are checked on every API call).
 */
export const SESSION_COOKIE = "isbree_portal_session";
export const DEVICE_COOKIE = "isbree_portal_device";

export type Session = {
  access: string;
  accessExpiresAt: number; // epoch ms
  refresh: string;
  refreshExpiresAt: number; // epoch ms
  sessionId: string;
};

let cachedKey: Uint8Array | null = null;

async function key(): Promise<Uint8Array> {
  if (cachedKey) return cachedKey;
  if (config.sessionSecret.length < 32) {
    throw new Error("PORTAL_SESSION_SECRET must be set (at least 32 characters).");
  }
  // A 256-bit key derived from the secret.
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(config.sessionSecret));
  cachedKey = new Uint8Array(digest);
  return cachedKey;
}

export async function sealSession(session: Session): Promise<string> {
  return new EncryptJWT({ s: session })
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .setExpirationTime(Math.floor(session.refreshExpiresAt / 1000))
    .encrypt(await key());
}

export async function unsealSession(value: string | undefined): Promise<Session | null> {
  if (!value) return null;
  try {
    const { payload } = await jwtDecrypt(value, await key());
    const s = payload.s as Session | undefined;
    if (!s || typeof s.access !== "string" || typeof s.refresh !== "string") return null;
    if (s.refreshExpiresAt <= Date.now()) return null;
    return s;
  } catch {
    return null; // tampered, foreign or expired
  }
}

export function sessionCookieOptions(session: Session) {
  return {
    httpOnly: true,
    secure: config.secureCookies,
    sameSite: "lax" as const,
    path: "/",
    expires: new Date(session.refreshExpiresAt),
  };
}

export function deviceCookieOptions() {
  return {
    httpOnly: true,
    secure: config.secureCookies,
    sameSite: "lax" as const,
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
  };
}

/** Django's token payload (login and refresh) -> session. */
export type TokenPayload = {
  access_token: string;
  access_expires_in: number;
  refresh_token: string;
  refresh_expires_at: string;
  session_id: string;
};

export function sessionFromTokens(tokens: TokenPayload, now = Date.now()): Session {
  return {
    access: tokens.access_token,
    accessExpiresAt: now + tokens.access_expires_in * 1000,
    refresh: tokens.refresh_token,
    refreshExpiresAt: new Date(tokens.refresh_expires_at).getTime(),
    sessionId: tokens.session_id,
  };
}

/** Refresh a little before Django's 15-minute access token expires. */
export function needsRefresh(session: Session, now = Date.now()) {
  return session.accessExpiresAt - now < 60_000;
}
