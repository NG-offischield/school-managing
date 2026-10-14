import type { ReactNode } from "react";

/** The title block of every inner page. */
export function PageHeader({ eyebrow, title, children }: { eyebrow?: string; title: string; children?: ReactNode }) {
  return (
    <header className="border-b border-line bg-sand/60">
      <div className="container-page py-12 sm:py-16">
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1 className="mt-2 max-w-3xl text-4xl sm:text-5xl">{title}</h1>
        {children ? <div className="mt-4 max-w-2xl text-lg text-muted">{children}</div> : null}
      </div>
    </header>
  );
}
