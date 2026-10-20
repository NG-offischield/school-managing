import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PortalHeader } from "@/components/portal-header";
import {
  Apps,
  ChildSelector,
  Empty,
  FaqList,
  News,
  Pages,
  PreEnrollments,
  Resources,
  Section,
} from "@/components/sections";
import { api } from "@/lib/dal";
import { formatPhone } from "@/lib/format";
import { getMe } from "@/lib/me";
import { type Role, roleFromSlug, ROLES } from "@/lib/roles";
import type { Child, PortalContext, Resource } from "@/lib/types";

export async function generateMetadata({ params }: PageProps<"/espace/[role]">): Promise<Metadata> {
  const role = roleFromSlug((await params).role);
  return { title: role ? ROLES[role].space : "Espace" };
}

const INTROS: Record<Role, string> = {
  PARENT: "Les informations de la classe de vos enfants, les démarches et les actualités de l'établissement.",
  TEACHER: "Vos ressources pédagogiques, les programmes de vos niveaux et les consignes de l'établissement.",
  STAFF: "Les informations, procédures et missions destinées au personnel.",
  GUARDIAN: "Les consignes, procédures d'accès et informations utiles à votre mission.",
};

export default async function SpacePage({ params, searchParams }: PageProps<"/espace/[role]">) {
  const role = roleFromSlug((await params).role);
  if (!role) notFound();
  const me = await getMe();
  if (!me) return <Unavailable />;

  // Django refuses (403) a role the user does not hold: the URL grants nothing.
  if (!me.roles.includes(role)) {
    return (
      <>
        <PortalHeader name={me.name} roles={me.roles} />
        <main id="contenu" tabIndex={-1} className="container-page flex-1 py-12 focus:outline-none">
          <h1 className="text-4xl">Espace non accessible</h1>
          <p className="mt-4 text-lg text-muted">Votre compte ne donne pas accès à l&apos;{ROLES[role].space}.</p>
          <Link href="/" className="btn btn-primary mt-6">
            Retour à mes espaces
          </Link>
        </main>
      </>
    );
  }

  const context = await api<PortalContext>("portal/context/", { role });
  if (!context.ok) return <Unavailable />;
  const ctx = context.data;

  // A parent: verified children only (Django), and the resources of the chosen one.
  let children: Child[] = [];
  let selected: string | null = null;
  let resources: Resource[] = ctx.resources;
  if (role === "PARENT") {
    const list = await api<Child[]>("parents/children/");
    children = list.ok ? list.data : [];
    const requested = (await searchParams).enfant;
    const wanted = typeof requested === "string" ? requested : null;
    selected = children.find((c) => c.student.id === wanted)?.student.id ?? children[0]?.student.id ?? null;
    if (selected) {
      const scoped = await api<Resource[]>("portal/resources/", { role, student: selected });
      if (scoped.ok) resources = scoped.data;
    }
  }
  const documentQuery = new URLSearchParams({ role, ...(selected ? { student: selected } : {}) }).toString();
  const selectedChild = children.find((c) => c.student.id === selected);

  return (
    <>
      <PortalHeader name={me.name} roles={me.roles} current={role} />
      <main id="contenu" tabIndex={-1} className="flex-1 focus:outline-none">
        <div className="border-b border-line bg-sand/50">
          <div className="container-page py-10">
            <p className="eyebrow">{ROLES[role].space}</p>
            <h1 className="mt-2 text-4xl">Bonjour {ctx.user.first_name}</h1>
            <p className="mt-3 max-w-2xl text-lg text-muted">{INTROS[role]}</p>
          </div>
        </div>
        <div className="container-page grid gap-12 py-10 lg:grid-cols-[1fr_20rem]">
          <div className="space-y-14">
            {role === "PARENT" ? (
              <Section id="enfants" title="Mes enfants">
                {children.length ? (
                  <ChildSelector items={children} selected={selected} role={role} />
                ) : (
                  <Empty>
                    Aucun enfant n&apos;est encore rattaché à votre compte. Le rattachement est fait par l&apos;établissement
                    après vérification : une préinscription acceptée ne le crée pas automatiquement.
                  </Empty>
                )}
              </Section>
            ) : null}
            {ctx.pre_enrollments.length ? (
              <Section id="preinscriptions" title="Mes demandes de préinscription">
                <PreEnrollments requests={ctx.pre_enrollments} />
              </Section>
            ) : null}
            <Section
              id="ressources"
              title={selectedChild ? `Ressources — ${selectedChild.student.first_name}` : "Ressources"}
              intro={
                role === "PARENT" && selectedChild
                  ? "Les informations générales et celles de la classe de l'enfant sélectionné."
                  : undefined
              }
            >
              <Resources resources={resources} documentQuery={documentQuery} />
            </Section>
            {ctx.apps.length ? (
              <Section
                id="applications"
                title="Applications mobiles"
                intro="L'application Android de votre rôle, à installer sur votre téléphone."
              >
                <Apps apps={ctx.apps} />
              </Section>
            ) : null}
            <Section id="actualites" title="Actualités">
              <News news={ctx.news} />
            </Section>
            <Section id="faq" title="Questions fréquentes">
              <FaqList faq={ctx.faq} />
            </Section>
          </div>
          <aside className="space-y-10 lg:sticky lg:top-6 lg:self-start">
            {ctx.pages.length ? (
              <Section id="informations" title="Informations">
                <Pages pages={ctx.pages} role={role} />
              </Section>
            ) : null}
            <Section id="contact" title="Contacter l'établissement">
              <div className="card space-y-2 p-5">
                {ctx.school.phone ? (
                  <p>
                    <a href={`tel:${ctx.school.phone.replace(/[^0-9+]/g, "")}`} className="link font-semibold">
                      {formatPhone(ctx.school.phone)}
                    </a>
                  </p>
                ) : null}
                {ctx.school.email ? (
                  <p className="break-all">
                    <a href={`mailto:${ctx.school.email}`} className="link">
                      {ctx.school.email}
                    </a>
                  </p>
                ) : null}
              </div>
            </Section>
          </aside>
        </div>
      </main>
    </>
  );
}

function Unavailable() {
  return (
    <main id="contenu" className="container-page py-16">
      <p role="alert" className="card p-6">
        Cet espace est momentanément indisponible. Réessayez dans quelques instants.
      </p>
    </main>
  );
}
