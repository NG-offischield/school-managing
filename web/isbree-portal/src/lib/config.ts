import { normalizeApiUrl, normalizeSiteUrl } from "./api-url";

/**
 * Server-side configuration of the portal (.env.example). Read on the server
 * only (no NEXT_PUBLIC_ variable): the session secret and the BFF token never
 * reach the browser. Kept free of "server-only" so proxy.ts can import it.
 */
const portalUrl = normalizeSiteUrl(process.env.ISBREE_PORTAL_URL, "http://localhost:3001");

export const config = {
  schoolCode: process.env.ISBREE_SCHOOL_CODE || "ISBREE",
  apiUrl: normalizeApiUrl(process.env.DJANGO_INTERNAL_API_URL),
  publicUrl: normalizeSiteUrl(process.env.ISBREE_PUBLIC_URL, "http://localhost:3000"),
  portalUrl,
  demoMode: process.env.ISBREE_DEMO_MODE === "true",
  // Public demo only: the shared password of the read-only fictitious accounts, shown on the
  // login page. Never a real account's password; never set outside the public demo.
  demoPassword: process.env.ISBREE_DEMO_MODE === "true" ? process.env.ISBREE_DEMO_SHARED_PASSWORD || "" : "",
  bffToken: process.env.WEB_BFF_TOKEN || "",
  sessionSecret: process.env.PORTAL_SESSION_SECRET || "",
  secureCookies: portalUrl.startsWith("https://"),
};
