import type { Metadata } from "next";
import Link from "next/link";

import { EditorialSection } from "@/components/editorial";
import { allIllustrations, Figure, IllustrationNote } from "@/components/figure";
import { NewsCard } from "@/components/news-card";
import { PageHeader } from "@/components/page-header";
import { getGallery, getNews } from "@/lib/api";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Vie scolaire",
  description: "Activités, événements et vie de l'établissement ISBREE.",
  path: "/vie-scolaire",
});

export default async function SchoolLifePage() {
  const [gallery, news] = await Promise.all([getGallery(), getNews()]);
  // Sport first, then class life; the first class picture already illustrates the home page.
  const byCategory = (category: string) => (gallery.ok ? gallery.data.filter((i) => i.category === category) : []);
  const pictures = [...byCategory("SPORTS"), ...byCategory("CLASSROOMS").slice(1)].slice(0, 4);
  const events = news.ok ? news.data.filter((n) => n.category === "EVENT" || n.category === "SCHOOL_LIFE").slice(0, 3) : [];
  return (
    <>
      <PageHeader eyebrow="Vie scolaire" title="La vie à ISBREE" />
      <div className="container-page space-y-16 py-14">
        <EditorialSection kind="SCHOOL_LIFE" />
        {pictures.length ? (
          <section aria-labelledby="images">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <h2 id="images" className="text-3xl">
                En images
              </h2>
              <Link href="/galerie" className="link font-semibold">
                Voir la galerie
              </Link>
            </div>
            <div className="mt-6 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              {pictures.map((image) => (
                <Figure
                  key={image.id}
                  image={image}
                  showCredit={!allIllustrations(pictures)}
                  sizes="(min-width: 1024px) 25vw, (min-width: 640px) 50vw, 100vw"
                />
              ))}
            </div>
            {allIllustrations(pictures) ? <IllustrationNote /> : null}
          </section>
        ) : null}
        {events.length ? (
          <section aria-labelledby="evenements">
            <h2 id="evenements" className="text-3xl">
              Événements
            </h2>
            <ul className="mt-6 grid gap-6 md:grid-cols-3">
              {events.map((article) => (
                <li key={article.slug}>
                  <NewsCard article={article} />
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </>
  );
}
