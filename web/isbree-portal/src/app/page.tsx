import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { PortalHeader } from "@/components/portal-header";
import { getMe } from "@/lib/me";
import { ROLES, spaceHref } from "@/lib/roles";

export const metadata: Metadata = { title: "Accueil" };

const DESCRIPTIONS = {
  PARENT: "Le suivi de vos enfants, les informations de leur classe et les démarches.",
  TEACHER: "Vos ressources pédagogiques, programmes et consignes.",
  STAFF: "Les informations, procédures et missions du personnel.",
  GUARDIAN: "Les consignes et procédures d'accès à l'établissement.",
} as const;

export default async function HomePage() {
  const me = await getMe();
  if (!me) {
    return (
      <main id="contenu" className="container-page py-16">
        <p role="alert" className="card p-6">
          L&apos;Espace ISBREE est momentanément indisponible. Réessayez dans quelques instants.
        </p>
      </main>
    );
  }
  if (me.roles.length === 1) redirect(spaceHref(me.roles[0]));
  return (
    <>
      <PortalHeader name={me.name} roles={me.roles} />
      <main id="contenu" tabIndex={-1} className="container-page flex-1 py-12 focus:outline-none">
        {me.roles.length === 0 ? (
          <>
            <h1 className="text-4xl">Aucun espace disponible</h1>
            <p className="mt-4 max-w-xl text-lg text-muted">
              Votre compte ne donne accès à aucun espace du portail (Parent, Enseignant, Personnel ou Gardien). Si vous
              pensez qu&apos;il s&apos;agit d&apos;une erreur, contactez l&apos;établissement.
            </p>
          </>
        ) : (
          <>
            <h1 className="text-4xl">Choisissez votre espace</h1>
            <p className="mt-3 text-lg text-muted">
              Votre compte donne accès à plusieurs espaces. Les informations de chacun restent séparées.
            </p>
            <ul className="mt-8 grid gap-5 sm:grid-cols-2">
              {me.roles.map((role) => (
                <li key={role}>
                  <Link href={spaceHref(role)} className="card group block h-full p-6 hover:border-ink">
                    <span className="eyebrow">{ROLES[role].label}</span>
                    <span className="mt-2 block font-serif text-2xl group-hover:underline">{ROLES[role].space}</span>
                    <span className="mt-2 block text-muted">{DESCRIPTIONS[role]}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </main>
    </>
  );
}
