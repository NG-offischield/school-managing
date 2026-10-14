import Link from "next/link";

export default function NotFound() {
  return (
    <div className="container-page py-20">
      <p className="eyebrow">Erreur 404</p>
      <h1 className="mt-2 text-4xl">Cette page n&apos;existe pas</h1>
      <p className="mt-4 max-w-xl text-lg text-muted">
        Elle a peut-être été déplacée ou retirée. Vous pouvez revenir à l&apos;accueil ou consulter les actualités.
      </p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link href="/" className="btn btn-primary">
          Retour à l&apos;accueil
        </Link>
        <Link href="/actualites" className="btn btn-secondary">
          Actualités
        </Link>
      </div>
    </div>
  );
}
