import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PortalHeader } from "@/components/portal-header";
import { Badge } from "@/components/sections";
import { api } from "@/lib/dal";
import { formatDate } from "@/lib/format";
import { Markup } from "@/lib/markup";
import { getMe } from "@/lib/me";
import { PORTAL_ROLES, type Role, ROLES, spaceHref } from "@/lib/roles";
import type { Page } from "@/lib/types";

export const metadata: Metadata = { title: "Information" };

/** An administrable page published for the chosen role (Django checks the role is held). */
export default async function PortalPage({ params, searchParams }: PageProps<"/pages/[slug]">) {
  const { slug } = await params;
  const requested = (await searchParams).role;
  const role = (PORTAL_ROLES as string[]).includes(String(requested)) ? (requested as Role) : null;
  const me = await getMe();
  if (!me || !role || !me.roles.includes(role)) notFound();
  const page = await api<Page>(`portal/pages/${encodeURIComponent(slug)}/`, { role });
  if (!page.ok) notFound();
  const p = page.data;
  return (
    <>
      <PortalHeader name={me.name} roles={me.roles} current={role} />
      <main id="contenu" tabIndex={-1} className="container-page flex-1 py-10 focus:outline-none">
        <nav aria-label="Fil d'Ariane" className="text-sm">
          <Link href={spaceHref(role)} className="link">
            {ROLES[role].space}
          </Link>
        </nav>
        <h1 className="mt-4 text-4xl">{p.title}</h1>
        <div className="mt-3 flex gap-2">
          {p.is_demo ? <Badge>Démonstration</Badge> : null}
          {p.to_validate ? <Badge tone="muted">Contenu provisoire, à valider par l&apos;établissement</Badge> : null}
        </div>
        <div className="mt-8">
          <Markup source={p.body} />
        </div>
        <p className="mt-8 text-sm text-muted">Dernière mise à jour : {formatDate(p.updated_at)}</p>
      </main>
    </>
  );
}
