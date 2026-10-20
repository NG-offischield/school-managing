import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ProvisionalNote, Unavailable } from "@/components/notices";
import { PageHeader } from "@/components/page-header";
import { getPage, getPages } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { config } from "@/lib/config";
import { Markup } from "@/lib/markup";
import { DEDICATED_ROUTES, pageMetadata } from "@/lib/seo";

/**
 * The other administrable pages: legal notice, privacy, terms, rules and any
 * "other" page. The pages with a dedicated route (about, admissions…) are
 * reachable here too, which is harmless: same public content.
 */
const NONE = "aucune-page";

/** A blocking route (params read outside <Suspense>), as Next.js recommends for it.
 * The 404 status of an unknown slug is set earlier, by src/proxy.ts. */
export const instant = false;

export async function generateStaticParams() {
  const pages = await getPages();
  const slugs = pages.ok ? pages.data.map((p) => ({ slug: p.slug })) : [];
  return slugs.length ? slugs : [{ slug: NONE }];
}

export async function generateMetadata({ params }: PageProps<"/informations/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const page = await getPage(slug);
  if (!page.ok) return { title: "Informations" };
  // A text also shown on a dedicated route (À propos, Vie scolaire...): that route is the canonical one.
  return pageMetadata({
    title: page.data.title,
    description: page.data.summary,
    path: DEDICATED_ROUTES[page.data.kind] ?? `/informations/${slug}`,
  });
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
        {config.demoMode && p.kind === "PRIVACY" ? <DemoPrivacy /> : null}
        <Markup source={p.body} />
        <ProvisionalNote show={Boolean(p.to_validate)} />
        {p.updated_at ? <p className="mt-8 text-sm text-muted">Dernière mise à jour : {formatDate(p.updated_at)}</p> : null}
      </div>
    </>
  );
}

/** What really happens to the data in the public demonstration (the policy below is the school's text). */
function DemoPrivacy() {
  return (
    <div role="note" className="mb-10 max-w-3xl rounded-xl border-l-4 border-ochre bg-ochre-soft p-5">
      <p className="font-semibold">Dans cette démonstration</p>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        <li>
          Une demande de préinscription est enregistrée dans la base de démonstration, hébergée gratuitement (Render,
          Neon), et visible par le compte d&apos;administration de démonstration.
        </li>
        <li>
          Elle n&apos;est transmise à personne et ne sert jamais à vous contacter : aucun e-mail ni SMS n&apos;est
          envoyé.
        </li>
        <li>La base peut être réinitialisée sans préavis : n&apos;y saisissez aucune donnée réelle.</li>
        <li>
          L&apos;Espace ISBREE n&apos;utilise que le cookie nécessaire à la connexion ; le site, aucun cookie de suivi.
        </li>
      </ul>
      <p className="mt-2">
        <Link href="/demonstration" className="link">
          En savoir plus sur cette démonstration
        </Link>
      </p>
    </div>
  );
}
