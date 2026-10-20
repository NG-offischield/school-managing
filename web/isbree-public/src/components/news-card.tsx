import Link from "next/link";

import { formatDate } from "@/lib/format";
import { NEWS_CATEGORIES, type NewsSummary } from "@/lib/types";

import { Figure } from "./figure";
import { LogoMark } from "./logo";

export function NewsCard({ article }: { article: NewsSummary }) {
  const date = article.event_date ? formatDate(article.event_date) : formatDate(article.published_at);
  return (
    <article className="card group relative flex h-full flex-col overflow-hidden">
      {article.cover ? (
        <Figure image={article.cover} showCaption={false} imageClassName="aspect-[16/9] w-full rounded-none object-cover" />
      ) : (
        <div aria-hidden="true" className="flex aspect-[16/9] items-center justify-center bg-ink">
          <LogoMark className="h-20 w-20 opacity-60" />
        </div>
      )}
      <div className="flex flex-1 flex-col gap-2 p-5">
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
          <span className="font-semibold text-terracotta">{NEWS_CATEGORIES[article.category] ?? "Actualité"}</span>
          {date ? (
            <>
              <span aria-hidden="true">·</span>
              <span>{article.event_date ? `Le ${date}` : date}</span>
            </>
          ) : null}
        </div>
        <h3 className="text-xl">
          <Link href={`/actualites/${article.slug}`} className="after:absolute after:inset-0 group-hover:underline">
            {article.title}
          </Link>
        </h3>
        <p className="text-muted">{article.summary}</p>
      </div>
    </article>
  );
}
