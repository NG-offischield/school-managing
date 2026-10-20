import Image from "next/image";

import type { ImageRef } from "@/lib/types";

/**
 * An image of the school's library, served by this site's /images route.
 * An illustration is always captioned as such: a stock or provided picture
 * is never presented as a photograph of ISBREE.
 */
export function imageSrc(image: Pick<ImageRef, "id">) {
  return `/images/${image.id}`;
}

export function Figure({
  image,
  className = "",
  imageClassName = "aspect-[4/3] w-full object-cover",
  sizes = "(min-width: 1024px) 33vw, 100vw",
  showCaption = true,
  showCredit = true,
  style,
}: {
  image: ImageRef;
  className?: string;
  imageClassName?: string;
  sizes?: string;
  showCaption?: boolean;
  /** false in a grid of illustrations that shows ONE IllustrationNote: the credit stays in the caption, read by screen readers only. */
  showCredit?: boolean;
  style?: React.CSSProperties;
}) {
  return (
    <figure className={className} style={style}>
      <Image
        src={imageSrc(image)}
        alt={image.alt_text}
        width={image.width ?? 800}
        height={image.height ?? 600}
        sizes={sizes}
        unoptimized
        className={`rounded-2xl bg-sand ${imageClassName}`}
      />
      {showCaption ? (
        <figcaption className="mt-2 text-sm text-muted">
          {image.caption ? <span className="text-ink">{image.caption}</span> : null}
          {image.is_illustration ? (
            // Always in the caption (ADR 0032); in a grid of illustrations it is shown once,
            // under the grid (IllustrationNote), and kept here for screen readers only.
            <span className={showCredit ? "block text-xs" : "sr-only"}>
              {image.credit || "Image d'illustration — ne représente pas ISBREE"}
            </span>
          ) : image.credit ? (
            <span className="block text-xs">{image.credit}</span>
          ) : null}
        </figcaption>
      ) : null}
    </figure>
  );
}

/** Every image of the list is an illustration: say it once, under the list. */
export function allIllustrations(images: ImageRef[]) {
  return images.length > 0 && images.every((image) => image.is_illustration);
}

export function IllustrationNote() {
  return <p className="mt-4 text-sm text-muted">Images d&apos;illustration : elles ne représentent pas ISBREE.</p>;
}
