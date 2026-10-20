/** Honesty notices (ADR 0032): provisional texts, outages. The fictitious data of the
 * demonstration are stated once, in the footer and on /demonstration (site-footer.tsx). */

import { config } from "@/lib/config";

/** In the demonstration every text is provisional: the footer says it once instead. */
export function ProvisionalNote({ show = true }: { show?: boolean }) {
  if (!show || config.demoMode) return null;
  return (
    <p className="mt-6 text-sm italic text-muted" role="note">
      Texte provisoire, en attente de validation par l&apos;établissement.
    </p>
  );
}

export function Unavailable({ what = "Ce contenu" }: { what?: string }) {
  return (
    <div className="card p-6" role="status">
      <p className="font-semibold">{what} est momentanément indisponible.</p>
      <p className="mt-1 text-muted">Merci de réessayer dans quelques instants.</p>
    </div>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="card p-6 text-muted">{children}</div>;
}
