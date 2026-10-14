import type { ReactNode } from "react";

import { config } from "@/lib/config";

import { Logo } from "./logo";

/** Layout of the pages reached without a session (login, activation). */
export function AuthShell({ title, intro, children }: { title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col lg:flex-row">
      <aside className="relative overflow-hidden bg-ink text-paper lg:w-[42%]">
        <div aria-hidden="true" className="pointer-events-none absolute -bottom-32 -left-32 h-96 w-96 rounded-full border-[2.5rem] border-ochre/15" />
        <div className="relative flex h-full flex-col gap-8 px-6 py-8 sm:px-10 lg:py-14">
          <a href={config.publicUrl} className="self-start rounded-lg" aria-label="Site public d'ISBREE">
            <Logo inverted />
          </a>
          <div className="hidden lg:mt-auto lg:block">
            <p className="font-serif text-4xl leading-tight text-paper">Espace ISBREE</p>
            <p className="mt-4 max-w-sm text-sand">
              L&apos;espace personnel des familles, des enseignants, du personnel et des gardiens de l&apos;établissement.
            </p>
          </div>
        </div>
        <div className="band" aria-hidden="true" />
      </aside>
      <main id="contenu" tabIndex={-1} className="flex flex-1 items-start justify-center px-4 py-10 focus:outline-none sm:px-6 lg:items-center">
        <div className="w-full max-w-md">
          <h1 className="text-3xl sm:text-4xl">{title}</h1>
          {intro ? <div className="mt-3 text-muted">{intro}</div> : null}
          <div className="mt-8">{children}</div>
        </div>
      </main>
    </div>
  );
}
