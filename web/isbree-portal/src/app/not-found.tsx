import Link from "next/link";

export default function NotFound() {
  return (
    <main id="contenu" className="container-page flex-1 py-20">
      <p className="eyebrow">Erreur 404</p>
      <h1 className="mt-2 text-4xl">Page introuvable</h1>
      <p className="mt-4 max-w-xl text-lg text-muted">Cette page n&apos;existe pas ou n&apos;est pas accessible avec votre compte.</p>
      <Link href="/" className="btn btn-primary mt-8">
        Retour à mon espace
      </Link>
    </main>
  );
}
