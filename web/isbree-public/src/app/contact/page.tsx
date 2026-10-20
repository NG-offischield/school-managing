import type { Metadata } from "next";

import { Unavailable } from "@/components/notices";
import { PageHeader } from "@/components/page-header";
import { getSite } from "@/lib/api";
import { formatPhone, telHref } from "@/lib/format";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Contact",
  description: "Contacter ISBREE à Etoug-Ebe, Yaoundé : téléphone, e-mail et accès.",
  path: "/contact",
});

export default async function ContactPage() {
  const site = await getSite();
  if (!site.ok) {
    return (
      <>
        <PageHeader eyebrow="Contact" title="Nous contacter" />
        <div className="container-page py-14">
          <Unavailable what="Les coordonnées" />
          <p className="mt-6">
            Téléphone :{" "}
            <a href="tel:+237698686729" className="link">
              +237 698 686 729
            </a>
          </p>
        </div>
      </>
    );
  }
  const { school, profile, locations } = site.data;
  return (
    <>
      <PageHeader eyebrow="Contact" title="Nous contacter">
        <p>L&apos;établissement répond à vos questions sur les admissions, la vie scolaire et l&apos;Espace ISBREE.</p>
      </PageHeader>
      <div className="container-page grid gap-8 py-14 md:grid-cols-2">
        <section aria-labelledby="coordonnees" className="card p-6 sm:p-8">
          <h2 id="coordonnees" className="text-2xl">
            Coordonnées
          </h2>
          <dl className="mt-5 space-y-5">
            {school.phone ? (
              <div>
                <dt className="text-sm font-bold uppercase tracking-wider text-muted">Téléphone</dt>
                <dd className="mt-1">
                  <a href={telHref(school.phone)} className="link text-xl font-semibold">
                    {formatPhone(school.phone)}
                  </a>
                </dd>
              </div>
            ) : null}
            {school.email ? (
              <div>
                <dt className="text-sm font-bold uppercase tracking-wider text-muted">E-mail</dt>
                <dd className="mt-1 break-all">
                  <a href={`mailto:${school.email}`} className="link text-lg">
                    {school.email}
                  </a>
                </dd>
              </div>
            ) : null}
            <div>
              <dt className="text-sm font-bold uppercase tracking-wider text-muted">Localisation</dt>
              <dd className="mt-1">
                {profile.address || profile.location_details || school.city}
                {!profile.address_confirmed ? (
                  <span className="block text-sm text-muted">L&apos;adresse précise sera communiquée par l&apos;établissement.</span>
                ) : null}
              </dd>
            </div>
            <div>
              <dt className="text-sm font-bold uppercase tracking-wider text-muted">Horaires d&apos;accueil</dt>
              <dd className="mt-1">{profile.office_hours || "À confirmer par l'établissement."}</dd>
            </div>
          </dl>
        </section>
        {locations.length ? (
          <section aria-labelledby="lieux">
            <h2 id="lieux" className="text-2xl">
              {locations.length > 1 ? "Nos sites" : "Où nous trouver"}
            </h2>
            <ul className="mt-5 space-y-4">
              {locations.map((location) => (
                <li key={location.id} className="card p-5">
                  <p className="flex flex-wrap items-center gap-2 text-lg font-semibold">
                    {location.name}
                    {location.is_main ? <span className="text-sm font-normal text-muted">(site principal)</span> : null}
                  </p>
                  {location.description ? <p className="mt-1 text-muted">{location.description}</p> : null}
                  {location.address_text ? <p className="mt-1">{location.address_text}</p> : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </>
  );
}
