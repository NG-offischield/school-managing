import type { MetadataRoute } from "next";

/** The portal is private: nothing may be indexed (no sitemap). */
export default function robots(): MetadataRoute.Robots {
  return { rules: { userAgent: "*", disallow: "/" } };
}
