import type { Metadata } from "next";

import { AuthShell } from "@/components/auth-shell";
import { config } from "@/lib/config";

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
