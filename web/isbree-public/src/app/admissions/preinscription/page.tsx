import type { Metadata } from "next";
import Link from "next/link";

import { EmptyState, Unavailable } from "@/components/notices";
import { PageHeader } from "@/components/page-header";
import { getPages, getSite } from "@/lib/api";
import { config } from "@/lib/config";

import { PreEnrollmentForm } from "./pre-enrollment-form";

export const metadata: Metadata = {
  title: "Préinscription",
  description: "Formulaire de préinscription en ligne à ISBREE.",
};

export default async function PreEnrollmentPage() {
  const [site, pages] = await Promise.all([getSite(), getPages()]);
  const privacy = pages.ok ? pages.data.find((p) => p.kind === "PRIVACY") : undefined;
  const open = site.ok && site.data.levels.length > 0 && site.data.years.length > 0;
  return (
    <>
      <PageHeader eyebrow="Admissions" title="Demande de préinscription">
        <p>
          Cette demande ne vaut pas inscription. L&apos;établissement l&apos;examine et vous recontacte. Seules les
          informations utiles au traitement de la demande sont demandées.
        </p>
      </PageHeader>
      <div className="container-page max-w-3xl py-12">
        {config.demoMode ? (
          <div role="note" className="mb-8 rounded-xl border-2 border-ochre bg-ochre-soft p-5">
            <p className="font-semibold">Démonstration : ce formulaire n&apos;est pas le système d&apos;admission d&apos;ISBREE.</p>
            <p className="mt-1">
              Les demandes envoyées ici ne sont jamais transmises à l&apos;établissement. Saisissez uniquement des
              informations fictives : n&apos;indiquez ni vrai nom, ni vrai téléphone, ni vraie adresse e-mail.
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
          />
        )}
      </div>
    </>
  );
}
