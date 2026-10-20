import Link from "next/link";

import { logout } from "@/lib/auth-actions";
import { config } from "@/lib/config";
import { type Role, ROLES, spaceHref } from "@/lib/roles";

import { Logo } from "./logo";

/**
 * Header of the authenticated pages. The role switcher only lists roles the
 * user really holds (from Django); the active one is marked as current.
 */
export function PortalHeader({ name, roles, current }: { name: string; roles: Role[]; current?: Role }) {
  return (
    <header className="border-b border-line bg-paper">
      <div className="container-page flex flex-wrap items-center justify-between gap-4 py-4">
        <Link href="/" className="rounded-lg" aria-label="Espace ISBREE — accueil">
          <Logo />
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          {/* Back to the public site: a plain link, the two sites share no session. */}
          <a href={config.publicUrl} className="link text-sm font-semibold">
            Site ISBREE
          </a>
          <p className="text-sm text-muted">
            Connecté : <span className="font-semibold text-ink">{name}</span>
          </p>
          <form action={logout}>
            <button type="submit" className="btn btn-secondary !min-h-10 !py-1.5 text-sm">
              Se déconnecter
            </button>
          </form>
        </div>
      </div>
      {roles.length > 1 ? (
        <nav aria-label="Choix de l'espace" className="border-t border-line bg-sand/50">
          <ul className="container-page flex flex-wrap gap-2 py-2">
            {roles.map((role) => (
              <li key={role}>
                <Link
                  href={spaceHref(role)}
                  aria-current={role === current ? "page" : undefined}
                  className={`inline-flex min-h-10 items-center rounded-full px-4 text-sm font-semibold ${
                    role === current ? "bg-ink text-paper" : "text-ink hover:bg-sand"
                  }`}
                >
                  {ROLES[role].space}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
      <div className="band" aria-hidden="true" />
    </header>
  );
}
