import "server-only";

import { normalizeApiUrl, normalizeSiteUrl } from "./api-url";

/**
 * Server-side configuration, read from the environment only (.env.example).
 * Nothing here is ever sent to the browser: WEB_BFF_TOKEN in particular is a
 * server-to-server secret proving to Django that the request comes from this
 * web server (ADR 0032).
 */
export const config = {
  schoolCode: process.env.ISBREE_SCHOOL_CODE || "ISBREE",
  apiUrl: normalizeApiUrl(process.env.DJANGO_INTERNAL_API_URL),
  publicUrl: normalizeSiteUrl(process.env.ISBREE_PUBLIC_URL, "http://localhost:3000"),
  portalUrl: normalizeSiteUrl(process.env.ISBREE_PORTAL_URL, "http://localhost:3001"),
  demoMode: process.env.ISBREE_DEMO_MODE === "true",
  bffToken: process.env.WEB_BFF_TOKEN || "",
};
