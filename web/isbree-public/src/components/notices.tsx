/** Honesty notices (ADR 0032): demo data, provisional texts, illustrations, outages. */

export function DemoBanner() {
  return (
    <div className="border-b border-line bg-sand/70 text-ink" role="note">
      <p className="container-page py-1.5 text-center text-xs">
        Site de démonstration : les éléments marqués « Démo » sont fictifs.
      </p>
    </div>
  );
}

export function DemoBadge({ show = true }: { show?: boolean }) {
  if (!show) return null;
  return (
    <span
      className="inline-flex items-center rounded-full border border-line px-2 py-0.5 text-[0.7rem] font-semibold uppercase tracking-wide text-muted"
      title="Contenu fictif de démonstration"
    >
      Démo
    </span>
  );
}

export function ProvisionalNote({ show = true }: { show?: boolean }) {
  if (!show) return null;
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
