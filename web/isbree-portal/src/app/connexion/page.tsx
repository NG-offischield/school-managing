import type { Metadata } from "next";

import { AuthShell } from "@/components/auth-shell";
import { config } from "@/lib/config";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Connexion" };

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
