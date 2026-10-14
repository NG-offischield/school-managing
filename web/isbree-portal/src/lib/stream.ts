import "server-only";

import { cookies } from "next/headers";

import { clientIp } from "./client-ip";
import { djangoHeaders, djangoUrl } from "./django";
import { SESSION_COOKIE, unsealSession } from "./session";

/**
 * Streams a protected file (resource PDF, application APK) from Django to the
 * browser. Django checks the session, the role and the scope; this handler
 * only relays, never caches ("private, no-store") and forwards a filtered set
 * of headers.
 */
const ALLOWED_TYPES = new Set(["application/pdf", "application/vnd.android.package-archive"]);

export async function relayFile(request: Request, path: string, query: Record<string, string> = {}) {
  const session = await unsealSession((await cookies()).get(SESSION_COOKIE)?.value);
  if (!session) return Response.redirect(new URL("/connexion", request.url), 303);
  const url = new URL(djangoUrl(path));
  for (const [name, value] of Object.entries(query)) if (value) url.searchParams.set(name, value);
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      // Accept */*: DRF content negotiation runs before the file view.
      headers: { ...djangoHeaders({ token: session.access, clientIp: clientIp(request.headers.get("x-forwarded-for")) }), Accept: "*/*" },
      cache: "no-store",
    });
  } catch {
    return text("Service momentanément indisponible.", 503);
  }
  if (upstream.status === 401) return Response.redirect(new URL("/connexion?session=expiree", request.url), 303);
  if (upstream.status === 429) return text("Trop de téléchargements. Réessayez plus tard.", 429);
  if (upstream.status === 403 || upstream.status === 404) return text("Ce fichier n'est pas disponible pour votre compte.", 404);
  const type = (upstream.headers.get("content-type") || "").split(";")[0].trim();
  if (!upstream.ok || !upstream.body || !ALLOWED_TYPES.has(type)) return text("Fichier indisponible.", 502);
  const headers = new Headers({
    "Content-Type": type,
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
  });
  for (const name of ["content-length", "content-disposition"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(upstream.body, { status: 200, headers });
}

function text(message: string, status: number) {
  return new Response(message, { status, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } });
}
