import type { Metadata } from "next";

import { allIllustrations, Figure } from "@/components/figure";
import { EmptyState, Unavailable } from "@/components/notices";
import { PageHeader } from "@/components/page-header";
import { getGallery } from "@/lib/api";
import { IMAGE_CATEGORIES, type ImageRef } from "@/lib/types";

export const metadata: Metadata = {
  title: "Galerie",
  description: "Galerie d'images d'ISBREE.",
};

export default async function GalleryPage() {
  const gallery = await getGallery();
  const groups = new Map<string, ImageRef[]>();
  if (gallery.ok) {
    for (const image of gallery.data) groups.set(image.category, [...(groups.get(image.category) ?? []), image]);
  }
  const illustrations = gallery.ok && gallery.data.some((i) => i.is_illustration);
  // All of them illustrations: said once in the header, not under each picture.
  const onlyIllustrations = gallery.ok && allIllustrations(gallery.data);
  return (
    <>
      <PageHeader eyebrow="Galerie" title="En images">
        {illustrations ? (
          <p>
            {onlyIllustrations
              ? "Ces images sont des illustrations choisies pour présenter le site : elles ne sont pas des photographies d'ISBREE."
              : "Les images marquées « illustration » ont été choisies pour présenter le site : elles ne sont pas des photographies d'ISBREE."}
          </p>
        ) : null}
      </PageHeader>
      <div className="container-page space-y-14 py-14">
        {!gallery.ok ? (
          <Unavailable what="La galerie" />
        ) : groups.size === 0 ? (
          <EmptyState>Aucune image n&apos;est publiée pour le moment.</EmptyState>
        ) : (
          [...groups].map(([category, images]) => (
            <section key={category} aria-labelledby={`cat-${category}`}>
              <h2 id={`cat-${category}`} className="text-3xl">
                {IMAGE_CATEGORIES[category] ?? "Autres images"}
              </h2>
              <div className="mt-6 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
                {images.map((image) => (
                  <Figure key={image.id} image={image} showCredit={!onlyIllustrations} />
                ))}
              </div>
            </section>
          ))
        )}
      </div>
    </>
  );
}
