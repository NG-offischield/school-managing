import Link from "next/link";

import { config } from "@/lib/config";

import { Logo } from "./logo";
import { MainNav } from "./main-nav";

export function SiteHeader() {
  return (
    <header className="relative z-30 border-b border-line bg-paper/95 backdrop-blur">
      <div className="container-page flex min-h-20 items-center justify-between gap-4">
        <Link href="/" className="rounded-lg" aria-label="ISBREE — accueil">
          <Logo />
        </Link>
        <MainNav portalUrl={config.portalUrl} />
      </div>
      <div className="band" aria-hidden="true" />
    </header>
  );
}
