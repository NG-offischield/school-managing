import type { Metadata } from "next";

import { EditorialSection } from "@/components/editorial";
import { PageHeader } from "@/components/page-header";
import { getSite } from "@/lib/api";

export const metadata: Metadata = {
  title: "À propos",
  description: "Qui est ISBREE, ses valeurs et son approche pédagogique.",
};

export default async function AboutPage() {
  const site = await getSite();
  const values = site.ok ? site.data.profile.values : [];
  return (
    <>
      <PageHeader eyebrow="À propos" title="Qui sommes-nous ?">
        {site.ok && site.data.profile.presentation ? <p>{site.data.profile.presentation}</p> : null}
      </PageHeader>
      <div className="container-page grid gap-12 py-14 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-14">
          <EditorialSection kind="ABOUT" />
          <EditorialSection kind="PEDAGOGY" heading missing="L'approche pédagogique sera présentée prochainement." />
        </div>
        {values.length ? (
          <aside aria-labelledby="valeurs" className="lg:sticky lg:top-6 lg:self-start">
            <div className="card p-6">
              <h2 id="valeurs" className="text-2xl">
                Nos valeurs
              </h2>
              <ul className="mt-4 space-y-3">
                {values.map((value) => (
                  <li key={value} className="flex items-center gap-3 font-semibold">
                    <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full bg-ochre" />
                    {value}
                  </li>
                ))}
              </ul>
            </div>
          </aside>
        ) : null}
      </div>
    </>
  );
}
