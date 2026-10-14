/**
 * Server-side configuration of the portal (.env.example). Read on the server
 * only (no NEXT_PUBLIC_ variable): the session secret and the BFF token never
 * reach the browser. Kept free of "server-only" so proxy.ts can import it.
 */
function trimSlash(value: string) {
  return value.replace(/\/+$/, "");
}

export const config = {
  schoolCode: process.env.ISBREE_SCHOOL_CODE || "ISBREE",
  apiUrl: trimSlash(process.env.DJANGO_INTERNAL_API_URL || "http://localhost:8000/api/v1"),
  publicUrl: trimSlash(process.env.ISBREE_PUBLIC_URL || "http://localhost:3000"),
  portalUrl: trimSlash(process.env.ISBREE_PORTAL_URL || "http://localhost:3001"),
  demoMode: process.env.ISBREE_DEMO_MODE === "true",
  bffToken: process.env.WEB_BFF_TOKEN || "",
  sessionSecret: process.env.PORTAL_SESSION_SECRET || "",
  secureCookies: (process.env.ISBREE_PORTAL_URL || "").startsWith("https://"),
};
