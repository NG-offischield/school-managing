import { publicApiUrl, serverHeaders } from "@/lib/api";

/**
 * Serves a published public image of the school's library. The browser
 * never calls Django: this route fetches the file server-side (Django checks
 * it is PUBLISHED and PUBLIC) and streams it back with a public cache.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

export async function GET(_request: Request, { params }: RouteContext<"/images/[id]">) {
  const { id } = await params;
  if (!UUID.test(id)) return new Response("Not found", { status: 404 });
  let upstream: Response;
  try {
    upstream = await fetch(publicApiUrl(`images/${id}/`), {
      // DRF content negotiation refuses Accept: image/* (406) before the file view runs.
      headers: serverHeaders({ Accept: "*/*" }),
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
  } catch {
    return new Response("Unavailable", { status: 503, headers: { "Cache-Control": "no-store" } });
  }
  const type = (upstream.headers.get("content-type") || "").split(";")[0].trim();
  if (!upstream.ok || !upstream.body || !IMAGE_TYPES.has(type)) {
    const status = upstream.status === 404 ? 404 : 502;
    return new Response(status === 404 ? "Not found" : "Unavailable", {
      status,
      headers: { "Cache-Control": "no-store" },
    });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": type,
      "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
      "X-Content-Type-Options": "nosniff",
      "Content-Disposition": "inline",
    },
  });
}
