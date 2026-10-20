import type { Metadata } from "next";

import { EmptyState, ProvisionalNote, Unavailable } from "@/components/notices";
import { PageHeader } from "@/components/page-header";
import { getFaq } from "@/lib/api";
import { FAQ_CATEGORIES, type Faq } from "@/lib/types";

export const metadata: Metadata = {
  title: "Questions fréquentes",
  description: "Réponses aux questions fréquentes sur ISBREE, la préinscription et l'Espace ISBREE.",
};

export default async function FaqPage() {
  const faq = await getFaq();
  const groups = new Map<string, Faq[]>();
  if (faq.ok) {
    // Categories in their declared order.
    for (const category of Object.keys(FAQ_CATEGORIES)) {
      const entries = faq.data.filter((e) => e.category === category);
      if (entries.length) groups.set(category, entries);
    }
  }
  return (
    <>
      <PageHeader eyebrow="FAQ" title="Questions fréquentes" />
      <div className="container-page grid gap-10 py-14 lg:grid-cols-[14rem_1fr]">
        {groups.size > 1 ? (
          <nav aria-label="Catégories de questions" className="lg:sticky lg:top-6 lg:self-start">
            <ul className="flex flex-wrap gap-2 lg:flex-col">
              {[...groups.keys()].map((category) => (
                <li key={category}>
                  <a href={`#${category.toLowerCase()}`} className="inline-flex min-h-11 items-center rounded-full px-3 font-semibold hover:bg-sand">
                    {FAQ_CATEGORIES[category]}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        ) : (
          <div />
        )}
        <div className="space-y-12">
          {!faq.ok ? (
            <Unavailable what="La FAQ" />
          ) : groups.size === 0 ? (
            <EmptyState>Aucune question n&apos;est publiée pour le moment.</EmptyState>
          ) : (
            [...groups].map(([category, entries]) => (
              <section key={category} id={category.toLowerCase()} aria-labelledby={`h-${category}`} className="scroll-mt-6">
                <h2 id={`h-${category}`} className="text-3xl">
                  {FAQ_CATEGORIES[category]}
                </h2>
                <div className="mt-5 divide-y divide-line rounded-[var(--radius-card)] border border-line bg-paper">
                  {entries.map((entry) => (
                    <details key={entry.id} className="group p-5">
                      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 text-lg font-semibold">
                        <span>
                          {entry.question}
                        </span>
                        <span aria-hidden="true" className="text-2xl text-terracotta transition-transform group-open:rotate-45">
                          +
                        </span>
                      </summary>
                      <p className="mt-3 text-muted">{entry.answer}</p>
                    </details>
                  ))}
                </div>
              </section>
            ))
          )}
          <ProvisionalNote show={faq.ok && faq.data.some((e) => e.to_validate)} />
        </div>
      </div>
    </>
  );
}
