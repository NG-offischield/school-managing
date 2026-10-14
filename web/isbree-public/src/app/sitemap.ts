import type { MetadataRoute } from "next";

import { NAVIGATION } from "@/components/navigation";
import { getNews, getPages } from "@/lib/api";
import { config } from "@/lib/config";

/** Public pages only: the portal (Espace ISBREE) is a separate, non-indexed site. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [pages, news] = await Promise.all([getPages(), getNews()]);
  const base = config.publicUrl;
  const fixed = ["", ...NAVIGATION.map((n) => n.href), "/admissions/preinscription"].map((path) => ({
    url: `${base}${path}`,
  }));
  const information = pages.ok
    ? pages.data.map((p) => ({ url: `${base}/informations/${p.slug}` }))
    : [];
  const articles = news.ok
    ? news.data.map((n) => ({ url: `${base}/actualites/${n.slug}`, lastModified: n.published_at ?? undefined }))
    : [];
  return [...fixed, ...information, ...articles];
}
