import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { DemoBadge, ProvisionalNote, Unavailable } from "@/components/notices";
import { PageHeader } from "@/components/page-header";
import { getPage, getPages } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { Markup } from "@/lib/markup";

/**
 * The other administrable pages: legal notice, privacy, terms, rules and any
 * "other" page. The pages with a dedicated route (about, admissions…) are
 * reachable here too, which is harmless: same public content.
 */
const NONE = "aucune-page";

export async function generateStaticParams() {
  const pages = await getPages();
  const slugs = pages.ok ? pages.data.map((p) => ({ slug: p.slug })) : [];
  return slugs.length ? slugs : [{ slug: NONE }];
}

export async function generateMetadata({ params }: PageProps<"/informations/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const page = await getPage(slug);
  return page.ok ? { title: page.data.title, description: page.data.summary } : { title: "Informations" };
}

export default async function InformationPage({ params }: PageProps<"/informations/[slug]">) {
  const { slug } = await params;
  const page = await getPage(slug);
  if (!page.ok && page.status === 404) notFound();
  if (!page.ok) {
    return (
      <div className="container-page py-16">
        <Unavailable />
      </div>
    );
  }
  const p = page.data;
  return (
    <>
      <PageHeader eyebrow="Informations" title={p.title}>
        {p.summary ? <p>{p.summary}</p> : null}
      </PageHeader>
      <div className="container-page py-14">
        <DemoBadge show={p.is_demo} />
        <Markup source={p.body} />
        <ProvisionalNote show={Boolean(p.to_validate)} />
        {p.updated_at ? <p className="mt-8 text-sm text-muted">Dernière mise à jour : {formatDate(p.updated_at)}</p> : null}
      </div>
    </>
  );
}
