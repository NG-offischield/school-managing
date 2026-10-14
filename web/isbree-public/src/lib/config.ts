import "server-only";

/**
 * Server-side configuration, read from the environment only (.env.example).
 * Nothing here is ever sent to the browser: WEB_BFF_TOKEN in particular is a
 * server-to-server secret proving to Django that the request comes from this
 * web server (ADR 0032).
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
};
