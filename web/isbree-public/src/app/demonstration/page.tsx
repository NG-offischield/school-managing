import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { config } from "@/lib/config";

export const metadata: Metadata = {
  title: "À propos de cette démonstration",
  description: "Ce que montre la démonstration de la plateforme ISBREE, et ce qui y est fictif.",
};

/** Served in the public demonstration only (ISBREE_DEMO_MODE): what is fictitious,
 * what really runs, and what has no effect outside this environment. Every
 * statement matches the software's behaviour (ADR 0032, ADR 0033). */
export default function DemonstrationPage() {
  if (!config.demoMode) notFound();
  return (
    <>
      <PageHeader eyebrow="Informations" title="À propos de cette démonstration">
        <p>
          Ce site, l&apos;Espace ISBREE et les applications mobiles présentent une démonstration logicielle de la
          plateforme de gestion scolaire. Voici ce qui y est fictif et ce qui fonctionne réellement.
        </p>
      </PageHeader>
      <div className="container-page grid gap-12 py-14 lg:grid-cols-[1fr_20rem]">
        <div className="prose-isbree max-w-3xl">
          <h2>Des données fictives</h2>
          <p>
            Les élèves, familles, enseignants, personnels, classes, emplois du temps, notes, absences, factures,
            paiements, actualités et statistiques affichés ont été créés pour illustrer le fonctionnement de la
            plateforme. Ils ne correspondent pas aux données d&apos;un établissement scolaire réel : toute ressemblance
            avec des personnes existantes serait fortuite.
          </p>
          <ul>
            <li>Les résultats et les moyennes sont calculés à partir de notes inventées.</li>
            <li>Les montants des frais sont des exemples et ne constituent pas une grille tarifaire.</li>
            <li>Les photographies sont des images d&apos;illustration : elles ne montrent pas l&apos;établissement.</li>
            <li>
              Les textes de présentation, d&apos;admission et d&apos;information sont des propositions en attente de
              validation par l&apos;établissement.
            </li>
          </ul>

          <h2>Ce qui fonctionne réellement</h2>
          <ul>
            <li>
              Le site et l&apos;Espace ISBREE interrogent une véritable API, reliée à une base de données réservée à la
              démonstration, distincte de toute base de production.
            </li>
            <li>
              La connexion applique les vrais contrôles : mot de passe, session, droits selon le rôle (parent,
              enseignant, personnel, gardien). Un parent ne voit que les enfants dont le rattachement a été vérifié.
            </li>
            <li>Une demande de préinscription est réellement vérifiée, enregistrée et numérotée.</li>
          </ul>

          <h2>Ce qui n&apos;a aucun effet à l&apos;extérieur</h2>
          <ul>
            <li>Aucune demande n&apos;est transmise à l&apos;établissement et personne ne vous recontactera.</li>
            <li>Aucun e-mail ni SMS n&apos;est envoyé.</li>
            <li>Aucun paiement réel n&apos;a lieu : les paiements affichés sont enregistrés à titre d&apos;exemple.</li>
            <li>
              Les comptes de démonstration sont en consultation seule : toute modification (mot de passe, saisie,
              paiement) est refusée.
            </li>
            <li>
              Les applications Android proposées sont des versions de test (signées avec une clé de débogage), pas des
              versions officielles.
            </li>
          </ul>

          <h2>La préinscription dans cet environnement</h2>
          <ul>
            <li>Vous remplissez le formulaire avec des informations fictives : ni vrai nom, ni vrai téléphone.</li>
            <li>Le serveur vérifie la demande, l&apos;enregistre et vous remet une référence de la forme PRE-AAAA-NNNN.</li>
            <li>
              La demande reste dans la base de démonstration : aucune décision ne vous sera communiquée et aucune place
              n&apos;est réservée.
            </li>
          </ul>

          <h2>Hébergement</h2>
          <p>
            La démonstration est hébergée gratuitement : après une période d&apos;inactivité, le premier affichage peut
            prendre environ une minute. La base de démonstration peut être réinitialisée sans préavis.
          </p>
        </div>
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <div className="card space-y-4 p-6">
            <h2 className="text-2xl">Explorer</h2>
            <p className="text-muted">Les comptes de démonstration figurent sur la page de connexion de l&apos;Espace ISBREE.</p>
            <a href={`${config.portalUrl}/connexion`} className="btn btn-primary w-full justify-center">
              Ouvrir l&apos;Espace ISBREE
            </a>
            <Link href="/admissions/preinscription" className="btn btn-secondary w-full justify-center">
              Essayer la préinscription
            </Link>
          </div>
        </aside>
      </div>
    </>
  );
}
