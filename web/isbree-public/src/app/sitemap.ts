import type { MetadataRoute } from "next";

import { NAVIGATION } from "@/components/navigation";
import { getNews, getPages } from "@/lib/api";
import { config } from "@/lib/config";
import { DEDICATED_ROUTES } from "@/lib/seo";

/**
 * Public, canonical pages only (docs/seo.md): the portal (Espace ISBREE) is a
 * separate, non-indexed site, and the API is never listed. The fixed routes are
 * always there, even when the API is asleep; the information pages and news
 * come from the API, with their real publication date only.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [pages, news] = await Promise.all([getPages(), getNews()]);
  const base = config.publicUrl;
  const extra = config.demoMode ? ["/demonstration"] : [];
  const fixed = ["", ...NAVIGATION.map((n) => n.href), "/admissions/preinscription", ...extra].map((path) => ({
    url: `${base}${path}`,
  }));
  // A text also shown on a dedicated route (À propos, Vie scolaire...) is listed under that route only.
  const information = pages.ok
    ? pages.data.filter((p) => !(p.kind in DEDICATED_ROUTES)).map((p) => ({ url: `${base}/informations/${p.slug}` }))
    : [];
  const articles = news.ok
    ? news.data.map((n) => ({ url: `${base}/actualites/${n.slug}`, lastModified: n.published_at ?? undefined }))
    : [];
  return [...fixed, ...information, ...articles];
}
