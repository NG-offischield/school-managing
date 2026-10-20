import type { Metadata } from "next";

/**
 * Search metadata of the public site (docs/seo.md). Every public page declares
 * its own title, description and canonical URL (relative: resolved against
 * metadataBase = ISBREE_PUBLIC_URL, never the portal nor the API). The share
 * image is app/opengraph-image.tsx, used by every page.
 */
export const SITE_NAME = "ISBREE";

/** Administrable pages whose text is shown on a dedicated route: that route is
 * the canonical one, and /informations/<slug> is left out of the sitemap. */
export const DEDICATED_ROUTES: Record<string, string> = {
  ABOUT: "/a-propos",
  PEDAGOGY: "/a-propos",
  SCHOOL_LIFE: "/vie-scolaire",
  ADMISSIONS: "/admissions",
};

export function pageMetadata({
  title,
  description,
  path,
  type = "website",
}: {
  title: string;
  description: string;
  path: string;
  type?: "website" | "article";
}): Metadata {
  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: {
      type,
      locale: "fr_CM",
      siteName: SITE_NAME,
      title,
      description,
      url: path,
      // A page's own openGraph replaces the inherited one: the share image is named again here.
      images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "ISBREE — Etoug-Ebe, Yaoundé" }],
    },
  };
}
