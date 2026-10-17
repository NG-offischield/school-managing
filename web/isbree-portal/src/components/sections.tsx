import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

import { formatDate } from "@/lib/format";
import { Markup } from "@/lib/markup";
import { type DemoApk, demoApk } from "@/lib/mobile-apps";
import { type Role, ROLES } from "@/lib/roles";
import {
  type AppEntry,
  type Child,
  FAQ_CATEGORIES,
  type Faq,
  type NewsItem,
  type PageSummary,
  type PreEnrollmentStatus,
  type Resource,
  RESOURCE_KINDS,
} from "@/lib/types";

export function Badge({ children, tone = "ochre" }: { children: ReactNode; tone?: "ochre" | "forest" | "muted" }) {
  const tones = { ochre: "bg-ochre-soft text-ink", forest: "bg-forest-soft text-forest", muted: "bg-sand text-muted" };
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold ${tones[tone]}`}>{children}</span>;
}

export function Section({ id, title, intro, children }: { id: string; title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="scroll-mt-6">
      <h2 id={id} className="text-2xl sm:text-3xl">
        {title}
      </h2>
      {intro ? <div className="mt-2 text-muted">{intro}</div> : null}
      <div className="mt-5">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="card p-5 text-muted">{children}</p>;
}

function size(bytes: number | null) {
  if (!bytes) return "";
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} Mo` : `${Math.ceil(bytes / 1024)} Ko`;
}

export function Resources({ resources, documentQuery }: { resources: Resource[]; documentQuery: string }) {
  if (!resources.length) return <Empty>Aucune ressource n&apos;est publiée pour le moment.</Empty>;
  return (
    <ul className="grid gap-4 md:grid-cols-2">
      {resources.map((r) => {
        const scope = [r.school_class, r.level, r.academic_year, r.staff_function].filter(Boolean).join(" · ");
        return (
          <li key={r.id} className="card flex flex-col gap-2 p-5">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-semibold text-terracotta">{RESOURCE_KINDS[r.kind] ?? "Ressource"}</span>
              {scope ? <span className="text-muted">· {scope}</span> : null}
              {r.is_demo ? <Badge tone="muted">Démo</Badge> : null}
              {r.to_validate ? <Badge tone="muted">Provisoire</Badge> : null}
            </div>
            <h3 className="text-xl">{r.title}</h3>
            {r.body ? <Markup source={r.body} className="prose-isbree text-[0.97rem]" /> : null}
            {r.visible_until ? <p className="text-sm text-muted">Disponible jusqu&apos;au {formatDate(r.visible_until)}</p> : null}
            {r.has_document ? (
              <a href={`/ressources/${r.id}/document?${documentQuery}`} className="link mt-auto self-start font-semibold">
                Télécharger {r.document_name || "le document"} (PDF{r.document_size ? `, ${size(r.document_size)}` : ""})
              </a>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export function News({ news }: { news: NewsItem[] }) {
  if (!news.length) return <Empty>Aucune actualité pour le moment.</Empty>;
  return (
    <ul className="space-y-4">
      {news.map((n) => (
        <li key={n.slug} className="card p-5">
          <details>
            <summary className="cursor-pointer list-none">
              <span className="flex flex-wrap items-center gap-2 text-sm text-muted">
                {formatDate(n.event_date ?? n.published_at)}
                {n.is_demo ? <Badge tone="muted">Démo</Badge> : null}
              </span>
              <span className="mt-1 block font-serif text-xl">{n.title}</span>
              <span className="mt-1 block text-muted">{n.summary}</span>
              {n.body ? <span className="link mt-2 inline-block text-sm font-semibold">Lire la suite</span> : null}
            </summary>
            {n.body ? <Markup source={n.body} className="prose-isbree mt-4" /> : null}
          </details>
        </li>
      ))}
    </ul>
  );
}

export function FaqList({ faq }: { faq: Faq[] }) {
  if (!faq.length) return <Empty>Aucune question fréquente pour cet espace.</Empty>;
  return (
    <div className="divide-y divide-line rounded-[var(--radius-card)] border border-line bg-paper">
      {faq.map((entry) => (
        <details key={entry.id} className="group p-5">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 font-semibold">
            <span>
              <span className="block text-xs font-bold uppercase tracking-wider text-terracotta">
                {FAQ_CATEGORIES[entry.category] ?? "Question"}
              </span>
              {entry.question}
            </span>
            <span aria-hidden="true" className="text-2xl text-terracotta transition-transform group-open:rotate-45">
              +
            </span>
          </summary>
          <p className="mt-3 text-muted">{entry.answer}</p>
        </details>
      ))}
    </div>
  );
}

export function Pages({ pages, role }: { pages: PageSummary[]; role: Role }) {
  if (!pages.length) return null;
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {pages.map((p) => (
        <li key={p.slug}>
          <Link href={`/pages/${p.slug}?role=${role}`} className="card block h-full p-4 hover:border-ink">
            <span className="font-semibold">{p.title}</span>
            {p.summary ? <span className="mt-1 block text-sm text-muted">{p.summary}</span> : null}
          </Link>
        </li>
      ))}
    </ul>
  );
}

/**
 * Mobile applications of the roles held. Only a PUBLISHED release (a signed
 * release APK checked by Django) gets a download button; otherwise the
 * application is honestly announced as not yet available. Android only.
 */
export function Apps({ apps }: { apps: AppEntry[] }) {
  if (!apps.length) return null;
  return (
    <ul className="grid gap-4 md:grid-cols-2">
      {apps.map(({ app, label, release }) => (
        <li key={app} className="card p-5">
          <h3 className="text-xl">{label}</h3>
          {release ? (
            <>
              <p className="mt-1 text-sm text-muted">
                Version {release.version_name}
                {release.min_android ? ` · Android ${release.min_android} ou plus récent` : ""} · {size(release.size)}
                {release.published_at ? ` · publiée le ${formatDate(release.published_at)}` : ""}
              </p>
              {release.release_notes ? <p className="mt-3">{release.release_notes}</p> : null}
              <a href={`/applications/${release.id}/telecharger`} className="btn btn-primary mt-4">
                Télécharger pour Android (APK)
              </a>
              <details className="mt-3 text-sm text-muted">
                <summary className="cursor-pointer">Vérifier le fichier</summary>
                <p className="mt-2 break-all">
                  Paquet : {release.package}
                  <br />
                  Empreinte SHA-256 : <code>{release.sha256}</code>
                </p>
              </details>
            </>
          ) : demoApk(app) ? (
            <DemoApkCard apk={demoApk(app)!} />
          ) : (
            <p className="mt-2 text-muted">
              Cette application n&apos;est pas encore disponible au téléchargement. L&apos;établissement l&apos;annoncera dès
              qu&apos;une version officielle sera publiée.
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

/** A demonstration build hosted on GitHub Releases (lib/mobile-apps.ts). */
function DemoApkCard({ apk }: { apk: DemoApk }) {
  return (
    <>
      <div className="mt-2 flex items-start gap-3">
        {/* Same icon as the installed app. */}
        <Image src="/apps/ic_launcher.png" alt="" width={48} height={48} className="rounded-xl" />
        <div>
          <p>{apk.purpose}</p>
          <p className="mt-1 text-sm text-muted">
            Version {apk.versionName} · Android 10 ou plus récent · {size(apk.size)}
          </p>
        </div>
      </div>
      <a href={apk.url} className="btn btn-primary mt-4" rel="noopener noreferrer">
        Télécharger l&apos;APK de démonstration
      </a>
      <p className="mt-3 text-sm text-muted">
        Build de démonstration (signé avec une clé de débogage) : il se connecte au serveur de démonstration et
        n&apos;est pas une version officielle. Le fichier est public, hébergé sur GitHub.
      </p>
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer font-semibold">Installer sur Android</summary>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-muted">
          <li>Téléchargez le fichier APK depuis votre téléphone Android (environ {size(apk.size)}).</li>
          <li>Ouvrez-le depuis les téléchargements ou la notification.</li>
          <li>
            Si Android le demande, autorisez votre navigateur à installer des applications inconnues (Paramètres → Applications
            → accès spécial), puis revenez à l&apos;installation.
          </li>
          <li>Installez, puis ouvrez l&apos;application « {apk.label} ».</li>
          <li>Connectez-vous avec le même identifiant que dans l&apos;Espace ISBREE.</li>
        </ol>
        <p className="mt-2 text-muted">
          Une version déjà installée signée différemment doit être désinstallée avant cette installation.
        </p>
      </details>
      <details className="mt-2 text-sm text-muted">
        <summary className="cursor-pointer">Vérifier le fichier</summary>
        <p className="mt-2 break-all">
          Paquet : {apk.package}
          <br />
          Empreinte SHA-256 : <code>{apk.sha256}</code>
        </p>
      </details>
    </>
  );
}

const STATUS_TONE: Record<string, "ochre" | "forest" | "muted"> = { ACCEPTED: "forest", REJECTED: "muted" };

export function PreEnrollments({ requests }: { requests: PreEnrollmentStatus[] }) {
  if (!requests.length) return null;
  return (
    <ul className="space-y-4">
      {requests.map((r) => (
        <li key={r.reference} className="card p-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm">{r.reference}</span>
            <Badge tone={STATUS_TONE[r.status] ?? "ochre"}>{r.status_label}</Badge>
          </div>
          <p className="mt-2 font-semibold">
            {r.child} — {r.level}, {r.year}
          </p>
          <p className="text-sm text-muted">Demande envoyée le {formatDate(r.submitted_at)}</p>
          {r.message ? <p className="mt-3 rounded-lg bg-sand/60 p-3">Message de l&apos;établissement : {r.message}</p> : null}
          {r.status === "ACCEPTED" ? (
            <p className="mt-3 text-sm text-muted">
              Une préinscription acceptée n&apos;est pas une inscription définitive : l&apos;inscription se finalise avec
              l&apos;établissement. Le suivi de votre enfant apparaîtra ici une fois le lien vérifié par l&apos;établissement.
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export function ChildSelector({ items, selected, role }: { items: Child[]; selected: string | null; role: Role }) {
  return (
    <nav aria-label="Choix de l'enfant">
      <ul className="flex flex-wrap gap-2">
        {items.map((c) => {
          const current = c.student.id === selected;
          return (
            <li key={c.student.id}>
              <Link
                href={`/espace/${ROLES[role].slug}?enfant=${c.student.id}`}
                aria-current={current ? "page" : undefined}
                className={`flex min-h-12 flex-col justify-center rounded-2xl border px-4 py-2 ${
                  current ? "border-ink bg-ink text-paper" : "border-line bg-paper hover:border-ink"
                }`}
              >
                <span className="font-semibold">
                  {c.student.first_name} {c.student.last_name}
                </span>
                {c.enrollment ? (
                  <span className={`text-sm ${current ? "text-sand" : "text-muted"}`}>
                    {c.enrollment.class_name} · {c.enrollment.academic_year_name}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
