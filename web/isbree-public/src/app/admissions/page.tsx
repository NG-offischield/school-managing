import type { Metadata } from "next";
import Link from "next/link";

import { EditorialSection } from "@/components/editorial";
import { PageHeader } from "@/components/page-header";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Admissions",
  description: "Comment demander une place à ISBREE : les étapes de la préinscription en ligne.",
  path: "/admissions",
});

export default function AdmissionsPage() {
  return (
    <>
      <PageHeader eyebrow="Admissions" title="Admissions et préinscription">
        <p>La préinscription se fait en ligne. L&apos;établissement examine ensuite chaque demande.</p>
      </PageHeader>
      <div className="container-page grid gap-12 py-14 lg:grid-cols-[1fr_22rem]">
        <EditorialSection kind="ADMISSIONS" />
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <div className="card bg-ink p-6 text-paper">
            <h2 className="text-2xl text-paper">Prêt à commencer ?</h2>
            <p className="mt-3 text-sand">
              Le formulaire demande les coordonnées du responsable, l&apos;identité de l&apos;enfant et le niveau souhaité.
              Aucun paiement n&apos;est demandé en ligne.
            </p>
            <Link href="/admissions/preinscription" className="btn btn-light mt-5 w-full">
              Remplir la préinscription
            </Link>
          </div>
          <p className="mt-4 text-sm text-muted">
            Une question ? Consultez la{" "}
            <Link href="/faq" className="link">
              FAQ
            </Link>{" "}
            ou{" "}
            <Link href="/contact" className="link">
              contactez l&apos;établissement
            </Link>
            .
          </p>
        </aside>
      </div>
    </>
  );
}
