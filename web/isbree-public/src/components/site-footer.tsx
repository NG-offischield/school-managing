import { cacheLife } from "next/cache";
import Link from "next/link";

import { getPages, getSite } from "@/lib/api";
import { config } from "@/lib/config";
import { formatPhone, telHref } from "@/lib/format";
import { INFO_PAGES } from "@/lib/types";

import { Logo } from "./logo";
import { NAVIGATION } from "./navigation";

export async function SiteFooter() {
  "use cache";
  cacheLife("minutes");
  const [site, pages] = await Promise.all([getSite(), getPages()]);
  const school = site.ok ? site.data.school : null;
  const infoLinks = INFO_PAGES.flatMap(({ kind, label }) => {
    const page = pages.ok ? pages.data.find((p) => p.kind === kind) : undefined;
    return page ? [{ href: `/informations/${page.slug}`, label }] : [];
  });
  const year = new Date().getFullYear();

  return (
    <footer className="mt-auto bg-ink text-paper">
      <div className="band" aria-hidden="true" />
      <div className="container-page grid gap-10 py-14 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <Logo inverted />
          <p className="mt-5 max-w-sm text-sand">
            {site.ok && site.data.profile.tagline ? site.data.profile.tagline : "Établissement scolaire à Yaoundé"}
          </p>
          <address className="mt-5 space-y-1 not-italic">
            <p>{site.ok ? site.data.profile.location_details || "Etoug-Ebe, Yaoundé" : "Etoug-Ebe, Yaoundé"}</p>
            {school?.phone ? (
              <p>
                <a href={telHref(school.phone)} className="underline decoration-ochre underline-offset-4 hover:decoration-2">
                  {formatPhone(school.phone)}
                </a>
              </p>
            ) : null}
            {school?.email ? (
              <p>
                <a href={`mailto:${school.email}`} className="break-all underline decoration-ochre underline-offset-4 hover:decoration-2">
                  {school.email}
                </a>
              </p>
            ) : null}
          </address>
        </div>
        <nav aria-label="Plan du site">
          <h2 className="font-sans text-sm font-bold uppercase tracking-widest text-ochre">Découvrir</h2>
          <ul className="mt-4 space-y-2">
            {NAVIGATION.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className="hover:underline">
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div>
          <h2 className="font-sans text-sm font-bold uppercase tracking-widest text-ochre">Familles et équipes</h2>
          <ul className="mt-4 space-y-2">
            <li>
              <Link href="/admissions/preinscription" className="hover:underline">
                Préinscription en ligne
              </Link>
            </li>
            <li>
              <a href={config.portalUrl} className="hover:underline">
                Espace ISBREE
              </a>
            </li>
          </ul>
          {infoLinks.length ? (
            <>
              <h2 className="mt-8 font-sans text-sm font-bold uppercase tracking-widest text-ochre">Informations</h2>
              <ul className="mt-4 space-y-2">
                {infoLinks.map((link) => (
                  <li key={link.href}>
                    <Link href={link.href} className="hover:underline">
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      </div>
      {config.demoMode ? (
        <div className="border-t border-white/15">
          <div className="container-page py-6 text-sm text-sand">
            <p className="max-w-4xl" role="note">
              <strong className="text-paper">Démonstration logicielle.</strong> ISBREE présente ici une démonstration de
              sa plateforme de gestion scolaire. Les élèves, familles, personnels, classes, résultats, actualités,
              images, statistiques et opérations affichés sont fictifs : ils ont été créés pour illustrer le
              fonctionnement de la plateforme et ne correspondent pas aux données d&apos;un établissement scolaire
              réel. Les textes de présentation sont des propositions en attente de validation.{" "}
              <Link
                href="/demonstration"
                className="font-semibold text-paper underline decoration-ochre underline-offset-4 hover:decoration-2"
              >
                En savoir plus sur cette démonstration
              </Link>
            </p>
          </div>
        </div>
      ) : null}
      <div className="border-t border-white/15">
        <div className="container-page flex flex-col gap-2 py-5 text-sm text-sand sm:flex-row sm:justify-between">
          <p>© {year} ISBREE. Tous droits réservés.</p>
          <p>Logo provisoire, en attente du logo officiel de l&apos;établissement.</p>
        </div>
      </div>
    </footer>
  );
}
