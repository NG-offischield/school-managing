import "server-only";

import { cacheLife, cacheTag } from "next/cache";

import { config } from "./config";
import type { Faq, ImageRef, News, NewsSummary, Page, PageSummary, Site } from "./types";

/**
 * Read access to the public Django API. Every getter is a cached function
 * ("use cache"): the content is the same for every visitor (never personal),
 * refreshed every minute; a failure is retried after 30 seconds, so the site
 * recovers shortly after the backend does. A failure is returned, not
 * thrown: pages show an honest "temporarily unavailable" state.
 *
 * Lifetime of a FAILED read (API down or asleep, e.g. a free host waking up
 * during the build): retried 30 s later, yet still prerenderable. Shorter
 * lifetimes (cacheLife("seconds"): expire 1 min < 5 min) become "dynamic
 * holes" excluded from prerendering, which fails the build of these pages.
 */
const UNAVAILABLE = { stale: 30, revalidate: 30, expire: 300 };

export type Loaded<T> = { ok: true; data: T } | { ok: false; status: number };

export function serverHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json", ...extra };
  if (config.bffToken) headers["X-ISBREE-BFF"] = config.bffToken;
  return headers;
}

export function publicApiUrl(path: string) {
  return `${config.apiUrl}/public/${encodeURIComponent(config.schoolCode)}/${path}`;
}

async function load<T>(path: string): Promise<Loaded<T>> {
  try {
    const response = await fetch(publicApiUrl(path), {
      headers: serverHeaders(),
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) return { ok: false, status: response.status };
    const body = (await response.json()) as { data: T };
    return { ok: true, data: body.data };
  } catch {
    return { ok: false, status: 503 };
  }
}

export async function getSite(): Promise<Loaded<Site>> {
  "use cache";
  cacheTag("site");
  const result = await load<Site>("site/");
  if (result.ok) cacheLife("minutes");
  else cacheLife(UNAVAILABLE);
  return result;
}

export async function getPages(): Promise<Loaded<PageSummary[]>> {
  "use cache";
  cacheTag("pages");
  const result = await load<PageSummary[]>("pages/");
  if (result.ok) cacheLife("minutes");
  else cacheLife(UNAVAILABLE);
  return result;
}

export async function getPage(slug: string): Promise<Loaded<Page>> {
  "use cache";
  cacheTag("pages");
  const result = await load<Page>(`pages/${encodeURIComponent(slug)}/`);
  if (result.ok || result.status === 404) cacheLife("minutes");
  else cacheLife(UNAVAILABLE);
  return result;
}

/** The published page of a kind (ABOUT, ADMISSIONS…), or null if there is none. */
export async function getPageOfKind(kind: string): Promise<Loaded<Page | null>> {
  const pages = await getPages();
  if (!pages.ok) return pages;
  const summary = pages.data.find((p) => p.kind === kind);
  if (!summary) return { ok: true, data: null };
  const page = await getPage(summary.slug);
  return page.ok ? page : page.status === 404 ? { ok: true, data: null } : page;
}

export async function getFaq(): Promise<Loaded<Faq[]>> {
  "use cache";
  cacheTag("faq");
  const result = await load<Faq[]>("faq/");
  if (result.ok) cacheLife("minutes");
  else cacheLife(UNAVAILABLE);
  return result;
}

export async function getNews(): Promise<Loaded<NewsSummary[]>> {
  "use cache";
  cacheTag("news");
  const result = await load<NewsSummary[]>("news/?page_size=50");
  if (result.ok) cacheLife("minutes");
  else cacheLife(UNAVAILABLE);
  return result;
}

export async function getArticle(slug: string): Promise<Loaded<News>> {
  "use cache";
  cacheTag("news");
  const result = await load<News>(`news/${encodeURIComponent(slug)}/`);
  if (result.ok || result.status === 404) cacheLife("minutes");
  else cacheLife(UNAVAILABLE);
  return result;
}

export async function getGallery(): Promise<Loaded<ImageRef[]>> {
  "use cache";
  cacheTag("gallery");
  const result = await load<ImageRef[]>("gallery/");
  if (result.ok) cacheLife("minutes");
  else cacheLife(UNAVAILABLE);
  return result;
}
