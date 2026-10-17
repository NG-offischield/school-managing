import type { Metadata } from "next";

import { AuthShell } from "@/components/auth-shell";
import { config } from "@/lib/config";
import { wakeApiInBackground } from "@/lib/wake";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Connexion" };

// Public demonstration only (ISBREE_DEMO_MODE + ISBREE_DEMO_SHARED_PASSWORD): read-only fictitious accounts.
const DEMO_ACCOUNTS = [
  ["Parent", "parent.demo@isbree.test"],
  ["Enseignant", "enseignant.demo@isbree.test"],
  ["Personnel", "personnel.demo@isbree.test"],
  ["Gardien", "gardien.demo@isbree.test"],
] as const;

const NOTICES: Record<string, string> = {
  expiree: "Votre session a expiré ou a été fermée. Reconnectez-vous.",
};

export default async function LoginPage({ searchParams }: PageProps<"/connexion">) {
  const params = await searchParams;
  wakeApiInBackground();
  const notice = typeof params.session === "string" ? NOTICES[params.session] : undefined;
  const loggedOut = params.deconnexion === "1";
  return (
    <AuthShell
      title="Connexion"
      intro={<p>Accédez à votre Espace ISBREE avec l&apos;identifiant et le mot de passe choisis lors de l&apos;activation.</p>}
    >
      {notice || loggedOut ? (
        <p role="status" className="mb-6 rounded-xl border border-line bg-paper p-4">
          {notice ?? "Vous êtes déconnecté."}
        </p>
      ) : null}
      {config.demoMode && config.demoPassword ? (
        <section aria-labelledby="demo-accounts" className="mb-6 rounded-xl border-2 border-ochre bg-ochre-soft p-4 text-sm">
          <h2 id="demo-accounts" className="font-sans text-base font-bold">
            Comptes de démonstration (fictifs, consultation seule)
          </h2>
          <ul className="mt-2 space-y-1">
            {DEMO_ACCOUNTS.map(([role, identifier]) => (
              <li key={identifier}>
                {role} : <code className="break-all">{identifier}</code>
              </li>
            ))}
          </ul>
          <p className="mt-2">
            Mot de passe commun : <code className="break-all">{config.demoPassword}</code>
          </p>
        </section>
      ) : null}
      <LoginForm />
      <div className="mt-8 space-y-3 border-t border-line pt-6 text-sm text-muted">
        <p>
          <strong className="text-ink">Première connexion ?</strong> Utilisez le lien d&apos;invitation remis par
          l&apos;établissement : il vous permet de choisir votre mot de passe.
        </p>
        <div>
          <p>
            <strong className="text-ink">Pas encore de compte ?</strong> L&apos;Espace ISBREE est réservé aux personnes
            autorisées par l&apos;établissement : il n&apos;y a pas d&apos;inscription libre.
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            <li>
              Famille d&apos;un futur élève :{" "}
              <a href={`${config.publicUrl}/admissions/preinscription`} className="link">
                faites une demande de préinscription
              </a>
              . Si elle est acceptée, l&apos;établissement vous envoie une invitation. Une préinscription n&apos;est pas une
              inscription et ne donne accès à aucun dossier d&apos;élève.
            </li>
            <li>
              Parent d&apos;un élève déjà inscrit : demandez votre accès à l&apos;établissement. Le rattachement à votre enfant
              est vérifié par l&apos;établissement avant tout accès à ses informations.
            </li>
            <li>Enseignant, personnel ou gardien : votre compte est créé par l&apos;administration de l&apos;établissement.</li>
          </ul>
          <p className="mt-1">
            <a href={`${config.publicUrl}/contact`} className="link">
              Contacter l&apos;établissement
            </a>
          </p>
        </div>
        <p>
          <strong className="text-ink">Mot de passe oublié ?</strong> Contactez l&apos;établissement, qui pourra vous
          remettre un nouveau lien d&apos;activation.
        </p>
        <p>
          <a href={config.publicUrl} className="link">
            Retour au site d&apos;ISBREE
          </a>
        </p>
      </div>
    </AuthShell>
  );
}
