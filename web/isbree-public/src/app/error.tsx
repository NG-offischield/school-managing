"use client";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="container-page py-20" role="alert">
      <h1 className="text-4xl">Une erreur est survenue</h1>
      <p className="mt-4 max-w-xl text-lg text-muted">La page n&apos;a pas pu être affichée. Merci de réessayer.</p>
      <button type="button" onClick={reset} className="btn btn-primary mt-8">
        Réessayer
      </button>
    </div>
  );
}
