import Link from "next/link";

import { Figure } from "@/components/figure";
import { LogoMark } from "@/components/logo";
import { NewsCard } from "@/components/news-card";
import { ProvisionalNote, Unavailable } from "@/components/notices";
import { getGallery, getNews, getSite } from "@/lib/api";
import { formatPhone, telHref } from "@/lib/format";

const STEPS = [
  { title: "Préinscription en ligne", text: "Vous remplissez le formulaire : il ne prend que quelques minutes." },
  { title: "Examen de la demande", text: "L'établissement étudie votre demande et peut vous demander des précisions." },
  { title: "Réponse de l'établissement", text: "Vous êtes informé de la décision par l'établissement." },
  { title: "Votre Espace ISBREE", text: "Si la demande est acceptée, une invitation vous permet d'activer votre espace." },
];

export default async function HomePage() {
  const [site, news, gallery] = await Promise.all([getSite(), getNews(), getGallery()]);
  if (!site.ok) {
    return (
      <div className="container-page py-16">
        <h1 className="text-4xl">ISBREE</h1>
        <div className="mt-6">
          <Unavailable what="Le contenu du site" />
        </div>
      </div>
    );
  }
  const { school, profile, levels } = site.data;
  const pictures = gallery.ok
    ? [...gallery.data].sort((a, b) => Number(b.category === "CAMPUS") - Number(a.category === "CAMPUS")).slice(0, 3)
    : [];
  const latest = news.ok ? news.data.slice(0, 3) : [];

  return (
    <>
      {/* --- Hero ----------------------------------------------------------------------- */}
      <section className="relative overflow-hidden bg-ink text-paper">
        <div aria-hidden="true" className="pointer-events-none absolute -right-40 -top-40 h-[34rem] w-[34rem] rounded-full border-[3rem] border-ochre/15" />
        <div className="container-page relative grid items-center gap-12 py-16 md:py-24 lg:grid-cols-[1.15fr_1fr]">
          <div>
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-ochre">
              Établissement scolaire · {profile.location_details || school.city}
            </p>
            <h1 className="mt-4 text-4xl text-paper sm:text-5xl lg:text-6xl">
              {profile.tagline || "Apprendre, grandir et s'ouvrir au monde"}
            </h1>
            {profile.presentation ? <p className="mt-6 max-w-xl text-lg text-sand">{profile.presentation}</p> : null}
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/admissions/preinscription" className="btn btn-light">
                Demander une préinscription
              </Link>
              <Link href="/a-propos" className="btn text-paper shadow-[inset_0_0_0_2px_var(--color-sand)] hover:bg-ink-soft">
                Découvrir ISBREE
              </Link>
            </div>
          </div>
          {pictures.length ? (
            <div className="grid grid-cols-2 gap-3">
              {pictures.map((image, index) => (
                <Figure
                  key={image.id}
                  image={image}
                  showCaption={false}
                  className={index === 0 ? "col-span-2" : ""}
                  imageClassName={`w-full object-cover ${index === 0 ? "aspect-[16/9]" : "aspect-square"}`}
                  sizes="(min-width: 1024px) 40vw, 100vw"
                />
              ))}
              {pictures.some((p) => p.is_illustration) ? (
                <p className="col-span-2 text-xs text-sand">Images d&apos;illustration : elles ne représentent pas ISBREE.</p>
              ) : null}
            </div>
          ) : (
            <div className="hidden justify-center lg:flex">
              <LogoMark className="h-64 w-64 opacity-90" />
            </div>
          )}
        </div>
      </section>

      {/* --- Values --------------------------------------------------------------------- */}
      {profile.values.length ? (
        <section aria-labelledby="valeurs" className="container-page py-16 md:py-20">
          <p className="eyebrow">Ce qui nous guide</p>
          <h2 id="valeurs" className="mt-2 text-3xl sm:text-4xl">
            Nos valeurs
          </h2>
          <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            {profile.values.map((value, index) => (
              <li key={value} className="card flex flex-col gap-3 p-5">
                <span aria-hidden="true" className="font-serif text-3xl text-terracotta">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="text-lg font-semibold">{value}</span>
              </li>
            ))}
          </ol>
          <ProvisionalNote show={profile.to_validate} />
        </section>
      ) : null}

      {/* --- Pedagogy and levels ---------------------------------------------------------- */}
      <section className="bg-sand/70">
        <div className="container-page grid gap-10 py-16 md:py-20 lg:grid-cols-2">
          <div>
            <p className="eyebrow">Notre approche</p>
            <h2 className="mt-2 text-3xl sm:text-4xl">Accompagner chaque élève</h2>
            <p className="mt-5 text-lg">{profile.pedagogy || "L'approche pédagogique de l'établissement sera présentée prochainement."}</p>
            <Link href="/a-propos" className="link mt-5 inline-block font-semibold">
              En savoir plus sur ISBREE
            </Link>
          </div>
          <div className="card p-6 sm:p-8">
            <h2 className="text-2xl">Niveaux ouverts à la préinscription</h2>
            {levels.length ? (
              <ul className="mt-5 divide-y divide-line">
                {levels.map((level) => (
                  <li key={level.id} className="flex items-center justify-between gap-3 py-3">
                    <span className="font-semibold">{level.name}</span>
                    <span className="text-sm text-muted">{level.cycle}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 text-muted">Les niveaux proposés seront publiés prochainement par l&apos;établissement.</p>
            )}
            <Link href="/formations" className="link mt-5 inline-block font-semibold">
              Voir les formations
            </Link>
          </div>
        </div>
      </section>

      {/* --- Admissions steps ------------------------------------------------------------- */}
      <section aria-labelledby="etapes" className="container-page py-16 md:py-20">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">Admissions</p>
            <h2 id="etapes" className="mt-2 text-3xl sm:text-4xl">
              Rejoindre ISBREE en quatre étapes
            </h2>
          </div>
          <Link href="/admissions/preinscription" className="btn btn-primary">
            Commencer la préinscription
          </Link>
        </div>
        <ol className="mt-10 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((step, index) => (
            <li key={step.title} className="relative border-t-4 border-forest pt-5">
              <span className="text-sm font-bold text-forest">Étape {index + 1}</span>
              <h3 className="mt-1 text-xl">{step.title}</h3>
              <p className="mt-2 text-muted">{step.text}</p>
            </li>
          ))}
        </ol>
        <p className="mt-8 text-muted">
          Une préinscription acceptée n&apos;est pas une inscription définitive : l&apos;inscription se finalise avec
          l&apos;établissement.
        </p>
      </section>

      {/* --- News ------------------------------------------------------------------------- */}
      {latest.length ? (
        <section aria-labelledby="actualites" className="bg-paper">
          <div className="container-page py-16 md:py-20">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="eyebrow">À la une</p>
                <h2 id="actualites" className="mt-2 text-3xl sm:text-4xl">
                  Actualités
                </h2>
              </div>
              <Link href="/actualites" className="link font-semibold">
                Toutes les actualités
              </Link>
            </div>
            <ul className="mt-8 grid gap-6 md:grid-cols-3">
              {latest.map((article) => (
                <li key={article.slug}>
                  <NewsCard article={article} />
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}

      {/* --- Contact band ----------------------------------------------------------------- */}
      <section className="bg-forest text-paper">
        <div className="container-page flex flex-col gap-6 py-12 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-3xl text-paper">Une question ?</h2>
            <p className="mt-2 text-forest-soft">L&apos;établissement vous répond par téléphone ou par e-mail.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            {school.phone ? (
              <a href={telHref(school.phone)} className="btn btn-light">
                Appeler le {formatPhone(school.phone)}
              </a>
            ) : null}
            <Link href="/contact" className="btn text-paper shadow-[inset_0_0_0_2px_var(--color-paper)] hover:bg-white/10">
              Nous contacter
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
