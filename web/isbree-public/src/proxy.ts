import { type NextRequest, NextResponse } from "next/server";

import { normalizeApiUrl } from "./lib/api-url";

/**
 * A real 404 for an unknown news item or information page.
 *
 * With Cache Components, a slug unknown at build time is answered with the
 * prerendered shell first: the HTTP status (200) is sent before the page can
 * call notFound(), so visitors saw "page not found" with a 200. Here, before
 * rendering, the public API is asked whether the item exists (answer kept one
 * minute); an unknown one is rewritten to a path no route matches, which Next
 * answers with app/not-found.tsx and a 404. If the API does not answer quickly
 * (asleep on the free host), the page renders as before: never a false 404.
 */
const DETAIL = /^\/(actualites|informations)\/([^/]+)\/?$/;
const ENDPOINT = { actualites: "news", informations: "pages" } as const;
const TTL_MS = 60_000;
const known = new Map<string, { exists: boolean; at: number }>();

async function exists(section: keyof typeof ENDPOINT, slug: string): Promise<boolean | undefined> {
  const key = `${section}/${slug}`;
  const cached = known.get(key);
  if (cached && Date.now() - cached.at < TTL_MS) return cached.exists;
  const school = encodeURIComponent(process.env.ISBREE_SCHOOL_CODE || "ISBREE");
  const url = `${normalizeApiUrl(process.env.DJANGO_INTERNAL_API_URL)}/public/${school}/${ENDPOINT[section]}/${encodeURIComponent(slug)}/`;
  try {
    const response = await fetch(url, { headers: { Accept: "application/json" }, signal: AbortSignal.timeout(4000) });
    if (response.status !== 200 && response.status !== 404) return undefined;
    if (known.size > 500) known.clear();
    known.set(key, { exists: response.status === 200, at: Date.now() });
    return response.status === 200;
  } catch {
    return undefined; // no answer: let the page decide
  }
}

export async function proxy(request: NextRequest) {
  const match = DETAIL.exec(request.nextUrl.pathname);
  if (!match) return NextResponse.next();
  let slug: string;
  try {
    slug = decodeURIComponent(match[2]);
  } catch {
    return NextResponse.rewrite(new URL("/introuvable", request.url));
  }
  if ((await exists(match[1] as keyof typeof ENDPOINT, slug)) === false) {
    return NextResponse.rewrite(new URL("/introuvable", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/actualites/:slug", "/informations/:slug"],
};
