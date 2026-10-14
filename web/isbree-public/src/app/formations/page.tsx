import type { Metadata } from "next";
import Link from "next/link";

import { EmptyState, Unavailable } from "@/components/notices";
import { PageHeader } from "@/components/page-header";
import { getSite } from "@/lib/api";
import type { Level } from "@/lib/types";

export const metadata: Metadata = {
  title: "Formations",
  description: "Les niveaux ouverts à la préinscription à ISBREE.",
};

/** Only the levels the school really offers (Level.public_visible): nothing invented. */
export default async function FormationsPage() {
  const site = await getSite();
  const groups = new Map<string, Level[]>();
  if (site.ok) {
    for (const level of site.data.levels) {
      const cycle = level.cycle || "Autres niveaux";
      groups.set(cycle, [...(groups.get(cycle) ?? []), level]);
    }
  }
  return (
    <>
      <PageHeader eyebrow="Formations" title="Les niveaux proposés">
        <p>Les niveaux ci-dessous sont ceux que l&apos;établissement ouvre actuellement à la préinscription.</p>
      </PageHeader>
      <div className="container-page py-14">
        {!site.ok ? (
          <Unavailable what="La liste des niveaux" />
        ) : groups.size === 0 ? (
          <EmptyState>Les niveaux proposés seront publiés prochainement par l&apos;établissement.</EmptyState>
        ) : (
          <div className="grid gap-6 md:grid-cols-2">
            {[...groups].map(([cycle, levels]) => (
              <section key={cycle} aria-labelledby={`cycle-${cycle}`} className="card p-6">
                <h2 id={`cycle-${cycle}`} className="text-2xl">
                  {cycle}
                </h2>
                <ul className="mt-4 divide-y divide-line">
                  {levels.map((level) => (
                    <li key={level.id} className="py-3 text-lg font-semibold">
                      {level.name}
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
        {site.ok && site.data.years.length ? (
          <p className="mt-8 text-muted">
            Année{site.data.years.length > 1 ? "s" : ""} scolaire{site.data.years.length > 1 ? "s" : ""} ouverte
            {site.data.years.length > 1 ? "s" : ""} : {site.data.years.map((y) => y.name).join(", ")}.
          </p>
        ) : null}
        <div className="mt-10 flex flex-wrap gap-3">
          <Link href="/admissions/preinscription" className="btn btn-primary">
            Demander une préinscription
          </Link>
          <Link href="/faq" className="btn btn-secondary">
            Questions fréquentes
          </Link>
        </div>
      </div>
    </>
  );
}
