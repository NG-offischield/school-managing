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
}: {
  image: ImageRef;
  className?: string;
  imageClassName?: string;
  sizes?: string;
  showCaption?: boolean;
}) {
  return (
    <figure className={className}>
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
            <span className="block text-xs">{image.credit || "Image d'illustration — ne représente pas ISBREE"}</span>
          ) : image.credit ? (
            <span className="block text-xs">{image.credit}</span>
          ) : null}
        </figcaption>
      ) : null}
    </figure>
  );
}
