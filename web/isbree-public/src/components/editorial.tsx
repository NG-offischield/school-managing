import { getPageOfKind } from "@/lib/api";
import { Markup } from "@/lib/markup";

import { DemoBadge, EmptyState, ProvisionalNote, Unavailable } from "./notices";

/** The body of the administrable page of a kind, with its honesty notices. */
export async function EditorialSection({
  kind,
  heading,
  missing = "Ce contenu sera publié prochainement par l'établissement.",
}: {
  kind: string;
  heading?: boolean;
  missing?: string;
}) {
  const page = await getPageOfKind(kind);
  if (!page.ok) return <Unavailable />;
  if (!page.data) return <EmptyState>{missing}</EmptyState>;
  return (
    <section aria-labelledby={heading ? `page-${page.data.slug}` : undefined}>
      {heading ? (
        <h2 id={`page-${page.data.slug}`} className="mb-4 text-3xl">
          {page.data.title} <DemoBadge show={page.data.is_demo} />
        </h2>
      ) : null}
      <Markup source={page.data.body} />
      <ProvisionalNote show={Boolean(page.data.to_validate)} />
    </section>
  );
}
