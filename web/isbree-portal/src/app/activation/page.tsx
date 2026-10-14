import type { Metadata } from "next";

import { AuthShell } from "@/components/auth-shell";

import { ActivationForm } from "./activation-form";

export const metadata: Metadata = { title: "Activation du compte" };

export default function ActivationPage() {
  return (
    <AuthShell
      title="Activer mon compte"
      intro={<p>Le lien d&apos;invitation remis par l&apos;établissement est valable 48 heures et ne sert qu&apos;une fois.</p>}
    >
      <ActivationForm />
    </AuthShell>
  );
}
