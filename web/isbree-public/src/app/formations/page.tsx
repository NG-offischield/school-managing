import type { Metadata } from "next";
import Link from "next/link";

import { allIllustrations, Figure, IllustrationNote } from "@/components/figure";
import { EmptyState, Unavailable } from "@/components/notices";
import { PageHeader } from "@/components/page-header";
import { getGallery, getSite } from "@/lib/api";
import type { Level } from "@/lib/types";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Formations",
  description: "Les niveaux ouverts à la préinscription à ISBREE, de la 6e à la 3e, et les salles de classe.",
  path: "/formations",
});

/** Only the levels the school really offers (Level.public_visible): nothing invented. */
export default async function FormationsPage() {
  const [site, gallery] = await Promise.all([getSite(), getGallery()]);
  // Class pictures not used elsewhere (home page, school life): the last three.
  const classrooms = gallery.ok ? gallery.data.filter((i) => i.category === "CLASSROOMS").slice(-3) : [];
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
          // One cycle: its levels side by side, full width; several cycles: one card each, two by two.
          <div className={`grid gap-6 ${groups.size > 1 ? "md:grid-cols-2" : ""}`}>
            {[...groups].map(([cycle, levels]) => (
              <section key={cycle} aria-labelledby={`cycle-${cycle}`} className="card p-6">
                <h2 id={`cycle-${cycle}`} className="text-2xl">
                  {cycle}
                </h2>
                <ul
                  className={
                    groups.size > 1 ? "mt-4 divide-y divide-line" : "mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
                  }
                >
                  {levels.map((level) => (
                    <li
                      key={level.id}
                      className={
                        groups.size > 1
                          ? "py-3 text-lg font-semibold"
                          : "rounded-xl border border-line bg-paper px-4 py-3 text-lg font-semibold"
                      }
                    >
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
        {classrooms.length ? (
          <section aria-labelledby="salles" className="mt-14">
            <h2 id="salles" className="text-3xl">
              Les salles de classe
            </h2>
            <div className="mt-6 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {classrooms.map((image) => (
                <Figure
                  key={image.id}
                  image={image}
                  showCredit={!allIllustrations(classrooms)}
                  sizes="(min-width: 1024px) 33vw, (min-width: 640px) 50vw, 100vw"
                />
              ))}
            </div>
            {allIllustrations(classrooms) ? <IllustrationNote /> : null}
          </section>
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
