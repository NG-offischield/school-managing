import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Figure } from "@/components/figure";
import { Unavailable } from "@/components/notices";
import { getArticle, getNews } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { Markup } from "@/lib/markup";
import { pageMetadata } from "@/lib/seo";
import { NEWS_CATEGORIES } from "@/lib/types";

/** Cache Components needs at least one param: a placeholder when nothing is published (-> 404). */
const NONE = "aucune-actualite";

/** A blocking route (params read outside <Suspense>), as Next.js recommends for it.
 * The 404 status of an unknown slug is set earlier, by src/proxy.ts. */
export const instant = false;

export async function generateStaticParams() {
  const news = await getNews();
  const slugs = news.ok ? news.data.map((n) => ({ slug: n.slug })) : [];
  return slugs.length ? slugs : [{ slug: NONE }];
}

export async function generateMetadata({ params }: PageProps<"/actualites/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const article = await getArticle(slug);
  if (!article.ok) return { title: "Actualité" };
  return pageMetadata({
    title: article.data.title,
    description: article.data.summary,
    path: `/actualites/${slug}`,
    type: "article",
  });
}

export default async function ArticlePage({ params }: PageProps<"/actualites/[slug]">) {
  const { slug } = await params;
  const article = await getArticle(slug);
  if (!article.ok && article.status === 404) notFound();
  if (!article.ok) {
    return (
      <div className="container-page py-16">
        <Unavailable what="Cette actualité" />
      </div>
    );
  }
  const a = article.data;
  const date = formatDate(a.event_date ?? a.published_at);
  return (
    <article>
      <header className="border-b border-line bg-sand/60">
        <div className="container-page py-12 sm:py-16">
          <nav aria-label="Fil d'Ariane" className="text-sm">
            <Link href="/actualites" className="link">
              Actualités
            </Link>
          </nav>
          <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-muted">
            <span className="font-semibold text-terracotta">{NEWS_CATEGORIES[a.category] ?? "Actualité"}</span>
            {date ? <span>· {a.event_date ? `Le ${date}` : `Publié le ${date}`}</span> : null}
          </div>
          <h1 className="mt-3 max-w-3xl text-4xl sm:text-5xl">{a.title}</h1>
          <p className="mt-4 max-w-2xl text-lg text-muted">{a.summary}</p>
        </div>
      </header>
      <div className="container-page py-12">
        {a.cover ? (
          // Never wider than the picture itself (small illustrations would be blurred), at most 48rem.
          <Figure
            image={a.cover}
            className="mb-10 w-full"
            imageClassName="aspect-[4/3] w-full object-cover"
            sizes="(min-width: 768px) 48rem, 100vw"
            style={{ maxWidth: `min(48rem, ${a.cover.width ?? 768}px)` }}
          />
        ) : null}
        {a.body ? <Markup source={a.body} /> : null}
        <Link href="/actualites" className="link mt-10 inline-block font-semibold">
          ← Toutes les actualités
        </Link>
      </div>
    </article>
  );
}
