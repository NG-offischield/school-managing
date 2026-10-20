import type { Metadata } from "next";

import { NewsCard } from "@/components/news-card";
import { EmptyState, Unavailable } from "@/components/notices";
import { PageHeader } from "@/components/page-header";
import { getNews } from "@/lib/api";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Actualités",
  description: "Actualités et événements d'ISBREE : vie de l'établissement, rencontres avec les familles et temps forts de l'année.",
  path: "/actualites",
});

export default async function NewsPage() {
  const news = await getNews();
  return (
    <>
      <PageHeader eyebrow="Actualités" title="Actualités et événements" />
      <div className="container-page py-14">
        {!news.ok ? (
          <Unavailable what="La liste des actualités" />
        ) : news.data.length === 0 ? (
          <EmptyState>Aucune actualité n&apos;est publiée pour le moment.</EmptyState>
        ) : (
          <ul className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {news.data.map((article) => (
              <li key={article.slug}>
                <NewsCard article={article} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
