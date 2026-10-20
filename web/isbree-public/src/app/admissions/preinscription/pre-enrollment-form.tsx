"use client";

import Link from "next/link";
import { type FormEvent, useActionState, useEffect, useRef, useState } from "react";

import {
  type Field,
  FIELD_LABELS,
  type FieldErrors,
  readForm,
  type SubmitState,
  validate,
  type Values,
} from "@/lib/pre-enrollment";
import type { Choice, Level, Year } from "@/lib/types";

import { submitPreEnrollment } from "./actions";

type Props = {
  levels: Level[];
  years: Year[];
  relationships: Choice[];
  privacyHref: string | null;
  action?: typeof submitPreEnrollment;
  /** Public demonstration: the request stays in the demo database, nobody calls back. */
  demo?: boolean;
};

const initial: SubmitState = { status: "idle" };

export function PreEnrollmentForm({
  levels,
  years,
  relationships,
  privacyHref,
  action = submitPreEnrollment,
  demo = false,
}: Props) {
  const [state, formAction, pending] = useActionState(action, initial);
  const [localErrors, setLocalErrors] = useState<FieldErrors | null>(null);
  const summaryRef = useRef<HTMLDivElement>(null);
  const receivedRef = useRef<HTMLHeadingElement>(null);

  const serverErrors = state.status === "invalid" ? state.errors : {};
  const errors: FieldErrors = localErrors ?? serverErrors;
  const values: Values = state.status === "invalid" || state.status === "error" ? state.values : {};
  const errorList = Object.entries(errors) as [Field, string][];
  const message =
    localErrors && errorList.length
      ? "Certains champs sont à corriger."
      : state.status === "invalid" || state.status === "error"
        ? state.message
        : "";

  useEffect(() => {
    if (state.status === "received") receivedRef.current?.focus();
    else if (state.status === "invalid" || state.status === "error") summaryRef.current?.focus();
  }, [state]);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    const { values: current, consent } = readForm(new FormData(event.currentTarget));
    const checked = validate(current, consent);
    if (!checked.ok) {
      event.preventDefault();
      setLocalErrors(checked.errors);
      requestAnimationFrame(() => summaryRef.current?.focus());
      return;
    }
    setLocalErrors(null);
  }

  if (state.status === "received") {
    return (
      <div className="card p-6 sm:p-8" role="status">
        <h2 ref={receivedRef} tabIndex={-1} className="text-2xl text-forest">
          Votre demande a bien été reçue
        </h2>
        {state.reference ? (
          <p className="mt-3">
            Référence de votre demande : <strong className="font-mono text-lg">{state.reference}</strong>. Conservez-la :
            {demo ? "elle identifie la demande dans la base de démonstration." : "elle vous sera utile pour tout échange avec l'établissement."}
          </p>
        ) : null}
        {demo ? (
          <p className="mt-3">
            Cette demande est enregistrée dans la base de démonstration : elle n&apos;est pas transmise à
            l&apos;établissement et personne ne vous contactera.
          </p>
        ) : (
          <>
            <p className="mt-3">
              L&apos;établissement examine chaque demande. Vous serez contacté par téléphone ou par e-mail. Une
              préinscription n&apos;est pas une inscription définitive.
            </p>
            <p className="mt-3 text-muted">
              Aucun e-mail automatique n&apos;est envoyé à ce stade : la réponse vient directement de l&apos;établissement.
            </p>
          </>
        )}
        <Link href="/" className="btn btn-secondary mt-6">
          Retour à l&apos;accueil
        </Link>
      </div>
    );
  }

  const describedBy = (field: Field, hint?: boolean) =>
    [hint ? `${field}-hint` : "", errors[field] ? `${field}-error` : ""].filter(Boolean).join(" ") || undefined;

  const text = (field: Field, props: { type?: string; autoComplete?: string; required?: boolean; hint?: string; max?: string } = {}) => (
    <div>
      <label htmlFor={field} className="block font-semibold">
        {FIELD_LABELS[field]}
        {props.required === false ? <span className="font-normal text-muted"> (facultatif)</span> : null}
      </label>
      {props.hint ? (
        <p id={`${field}-hint`} className="text-sm text-muted">
          {props.hint}
        </p>
      ) : null}
      <input
        id={field}
        name={field}
        type={props.type ?? "text"}
        autoComplete={props.autoComplete}
        required={props.required !== false}
        max={props.max}
        defaultValue={values[field] ?? ""}
        aria-invalid={errors[field] ? true : undefined}
        aria-describedby={describedBy(field, Boolean(props.hint))}
        className="field mt-1"
      />
      {errors[field] ? (
        <p id={`${field}-error`} className="mt-1 text-sm font-semibold text-danger">
          {errors[field]}
        </p>
      ) : null}
    </div>
  );

  const select = (field: Field, options: { value: string; label: string }[], placeholder: string) => (
    <div>
      <label htmlFor={field} className="block font-semibold">
        {FIELD_LABELS[field]}
      </label>
      <select
        id={field}
        name={field}
        required
        defaultValue={values[field] ?? ""}
        aria-invalid={errors[field] ? true : undefined}
        aria-describedby={describedBy(field)}
        className="field mt-1"
      >
        <option value="">{placeholder}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {errors[field] ? (
        <p id={`${field}-error`} className="mt-1 text-sm font-semibold text-danger">
          {errors[field]}
        </p>
      ) : null}
    </div>
  );

  return (
    <form action={formAction} onSubmit={onSubmit} noValidate className="space-y-8" aria-describedby="form-intro">
      <p id="form-intro" className="text-muted">
        Tous les champs sont obligatoires, sauf mention « facultatif ».
      </p>

      {message ? (
        <div
          ref={summaryRef}
          tabIndex={-1}
          role="alert"
          className="rounded-xl border border-danger bg-danger-soft p-4 text-danger"
        >
          <p className="font-semibold">{message}</p>
          {errorList.length ? (
            <ul className="mt-2 list-disc pl-5">
              {errorList.map(([field, error]) => (
                <li key={field}>
                  <a href={`#${field}`} className="underline">
                    {error}
                  </a>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <fieldset className="card space-y-4 p-5 sm:p-6">
        <legend className="rounded-md bg-paper px-2 font-serif text-xl">Le responsable de l&apos;enfant</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          {text("guardian_first_name", { autoComplete: "given-name" })}
          {text("guardian_last_name", { autoComplete: "family-name" })}
          {text("guardian_phone", { type: "tel", autoComplete: "tel", hint: "Par exemple +237 6XX XX XX XX" })}
          {text("guardian_email", { type: "email", autoComplete: "email" })}
        </div>
        {select("relationship", relationships, "Choisir…")}
      </fieldset>

      <fieldset className="card space-y-4 p-5 sm:p-6">
        <legend className="rounded-md bg-paper px-2 font-serif text-xl">L&apos;enfant</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          {text("child_first_name", { autoComplete: "off" })}
          {text("child_last_name", { autoComplete: "off" })}
          {text("child_birth_date", { type: "date", required: false, autoComplete: "off" })}
          {text("previous_school", { required: false, autoComplete: "off" })}
        </div>
      </fieldset>

      <fieldset className="card space-y-4 p-5 sm:p-6">
        <legend className="rounded-md bg-paper px-2 font-serif text-xl">La demande</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          {select(
            "requested_level",
            levels.map((l) => ({ value: l.id, label: l.cycle ? `${l.name} — ${l.cycle}` : l.name })),
            "Choisir un niveau…",
          )}
          {select(
            "requested_year",
            years.map((y) => ({ value: y.id, label: y.name })),
            "Choisir une année…",
          )}
        </div>
        <div>
          <label htmlFor="comment" className="block font-semibold">
            {FIELD_LABELS.comment} <span className="font-normal text-muted">(facultatif)</span>
          </label>
          <p id="comment-hint" className="text-sm text-muted">
            1000 caractères au maximum. N&apos;indiquez aucune information médicale.
          </p>
          <textarea
            id="comment"
            name="comment"
            rows={4}
            maxLength={1000}
            defaultValue={values.comment ?? ""}
            aria-invalid={errors.comment ? true : undefined}
            aria-describedby={describedBy("comment", true)}
            className="field mt-1"
          />
          {errors.comment ? (
            <p id="comment-error" className="mt-1 text-sm font-semibold text-danger">
              {errors.comment}
            </p>
          ) : null}
        </div>
      </fieldset>

      {/* Honeypot: hidden from people and from assistive technologies. */}
      <div aria-hidden="true" className="absolute -left-[9999px] h-px w-px overflow-hidden">
        <label htmlFor="website">Ne pas remplir</label>
        <input id="website" name="website" type="text" tabIndex={-1} autoComplete="off" defaultValue="" />
      </div>

      <div className="card p-5 sm:p-6">
        <div className="flex items-start gap-3">
          <input
            id="consent"
            name="consent"
            type="checkbox"
            required
            className="mt-1 h-5 w-5 shrink-0 accent-[var(--color-forest)]"
            aria-invalid={errors.consent ? true : undefined}
            aria-describedby={describedBy("consent")}
          />
          <label htmlFor="consent">
            J&apos;accepte que ces informations soient utilisées par l&apos;établissement uniquement pour traiter cette
            demande de préinscription et me recontacter.
            {privacyHref ? (
              <>
                {" "}
                <Link href={privacyHref} className="link">
                  Lire la politique de confidentialité
                </Link>
                .
              </>
            ) : null}
          </label>
        </div>
        {errors.consent ? (
          <p id="consent-error" className="mt-2 text-sm font-semibold text-danger">
            {errors.consent}
          </p>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <button type="submit" className="btn btn-primary" disabled={pending}>
          {pending ? "Envoi en cours…" : "Envoyer ma demande"}
        </button>
        <p className="text-sm text-muted" aria-live="polite">
          {pending ? "Votre demande est en cours d'envoi." : ""}
        </p>
      </div>
    </form>
  );
}
