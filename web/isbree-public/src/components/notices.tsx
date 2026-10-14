/** Honesty notices (ADR 0032): demo data, provisional texts, illustrations, outages. */

export function DemoBanner() {
  return (
    <div className="bg-ochre-soft text-ink" role="note">
      <p className="container-page py-2 text-center text-sm font-semibold">
        Version de démonstration : certains contenus marqués « Démonstration » (lieux, actualités, comptes) sont fictifs.
      </p>
    </div>
  );
}

export function DemoBadge({ show = true }: { show?: boolean }) {
  if (!show) return null;
  return (
    <span className="inline-flex items-center rounded-full bg-ochre-soft px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-ink">
      Démonstration
    </span>
  );
}

export function ProvisionalNote({ show = true }: { show?: boolean }) {
  if (!show) return null;
  return (
    <p className="mt-6 rounded-xl border border-dashed border-terracotta/60 bg-paper px-4 py-3 text-sm text-muted" role="note">
      <strong className="text-terracotta">Contenu provisoire.</strong> Ce texte est une première proposition, en attente de
      relecture et de validation par l&apos;établissement.
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
