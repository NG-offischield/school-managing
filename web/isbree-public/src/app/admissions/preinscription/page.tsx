import type { Metadata } from "next";
import Link from "next/link";

import { EmptyState, Unavailable } from "@/components/notices";
import { PageHeader } from "@/components/page-header";
import { getPages, getSite } from "@/lib/api";
import { config } from "@/lib/config";
import { pageMetadata } from "@/lib/seo";

import { PreEnrollmentForm } from "./pre-enrollment-form";

export const metadata: Metadata = pageMetadata({
  title: "Préinscription",
  description: "Formulaire de demande de préinscription en ligne à ISBREE, pour les niveaux de la 6e à la 3e.",
  path: "/admissions/preinscription",
});

export default async function PreEnrollmentPage() {
  const [site, pages] = await Promise.all([getSite(), getPages()]);
  const privacy = pages.ok ? pages.data.find((p) => p.kind === "PRIVACY") : undefined;
  const open = site.ok && site.data.levels.length > 0 && site.data.years.length > 0;
  return (
    <>
      <PageHeader eyebrow="Admissions" title="Demande de préinscription">
        <p>
          Cette demande ne vaut pas inscription.{" "}
          {config.demoMode ? "" : "L'établissement l'examine et vous recontacte. "}Seules les informations utiles au
          traitement de la demande sont demandées.
        </p>
      </PageHeader>
      <div className="container-page max-w-3xl py-12">
        {config.demoMode ? (
          <div role="note" className="mb-8 rounded-xl border-l-4 border-ochre bg-ochre-soft p-5">
            <p className="font-semibold">Formulaire de démonstration</p>
            <p className="mt-1">
              Votre demande sera enregistrée et numérotée dans la base de démonstration, sans être transmise à
              l&apos;établissement : personne ne vous recontactera. Saisissez uniquement des informations fictives, ni vrai
              nom, ni vrai téléphone, ni vraie adresse e-mail.{" "}
              <Link href="/demonstration" className="link">
                En savoir plus
              </Link>
            </p>
          </div>
        ) : null}
        {!site.ok ? (
          <Unavailable what="Le formulaire de préinscription" />
        ) : !open ? (
          <EmptyState>
            La préinscription en ligne n&apos;est pas ouverte pour le moment. Vous pouvez{" "}
            <Link href="/contact" className="link">
              contacter l&apos;établissement
            </Link>
            .
          </EmptyState>
        ) : (
          <PreEnrollmentForm
            levels={site.data.levels}
            years={site.data.years}
            relationships={site.data.relationships}
            privacyHref={privacy ? `/informations/${privacy.slug}` : null}
            demo={config.demoMode}
          />
        )}
      </div>
    </>
  );
}
