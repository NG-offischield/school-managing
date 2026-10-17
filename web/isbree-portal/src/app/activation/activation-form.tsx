"use client";

import Link from "next/link";
import { startTransition, useActionState, useEffect, useRef } from "react";

import { type ActivationState, checkActivation, completeActivation } from "@/lib/auth-actions";
import { formatDate } from "@/lib/format";

type Actions = { check: typeof checkActivation; complete: typeof completeActivation };

/**
 * The invitation link is {portal}/activation#code=…: the code travels in the
 * URL FRAGMENT, which browsers never send to a server nor put in a Referer.
 * It is read here, removed from the address bar, and sent to the server
 * action only in a POST body.
 */
export function readCodeFromHash(hash: string) {
  const match = hash.replace(/^#/, "").match(/(?:^|&)code=([^&]+)/);
  return match ? decodeURIComponent(match[1]).trim().slice(0, 64) : "";
}

export function ActivationForm({ actions = { check: checkActivation, complete: completeActivation } }: { actions?: Actions }) {
  const [state, dispatch, pending] = useActionState(
    async (previous: ActivationState, form: FormData) =>
      form.get("intent") === "check" ? actions.check(previous, form) : actions.complete(previous, form),
    { step: "code" } as ActivationState,
  );
  const started = useRef(false);
  const alertRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const check = () => {
      const code = readCodeFromHash(window.location.hash);
      if (window.location.hash) window.history.replaceState(null, "", window.location.pathname);
      const form = new FormData();
      form.set("intent", "check");
      form.set("code", code);
      startTransition(() => dispatch(form));
    };
    if (!started.current) {
      started.current = true;
      check();
    }
    // Another link opened while this page is shown: only the fragment changes, no reload.
    const onHash = () => {
      if (readCodeFromHash(window.location.hash)) check();
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [dispatch]);

  useEffect(() => {
    if ("error" in state && state.error) alertRef.current?.focus();
    else if (state.step !== "code") headingRef.current?.focus();
  }, [state]);

  if (state.step === "done") {
    return (
      <div role="status" className="card p-6">
        <h2 ref={headingRef} tabIndex={-1} className="text-2xl text-forest">
          Votre compte est activé
        </h2>
        <p className="mt-3">
          Votre identifiant de connexion : <strong className="break-all">{state.login}</strong>
        </p>
        <p className="mt-2 text-muted">Ce lien d&apos;activation ne peut plus être utilisé.</p>
        <Link href="/connexion" className="btn btn-primary mt-6 w-full">
          Se connecter
        </Link>
      </div>
    );
  }

  if (state.step === "code") {
    return pending || !state.error ? (
      <p role="status" className="card p-6">
        Vérification de votre lien d&apos;activation…
      </p>
    ) : (
      <div ref={alertRef} tabIndex={-1} role="alert" className="rounded-xl border border-danger bg-danger-soft p-5 text-danger">
        <p className="font-semibold">{state.error}</p>
        {state.retryCode ? (
          <form action={dispatch} className="mt-4">
            <input type="hidden" name="intent" value="check" />
            <input type="hidden" name="code" value={state.retryCode} />
            <button type="submit" className="btn btn-primary">
              Réessayer
            </button>
          </form>
        ) : (
          <Link href="/connexion" className="mt-4 inline-block underline">
            Aller à la page de connexion
          </Link>
        )}
      </div>
    );
  }

  const errors = state.fieldErrors ?? {};
  return (
    <form action={dispatch} className="space-y-5" noValidate>
      <input type="hidden" name="intent" value="complete" />
      <div>
        <h2 ref={headingRef} tabIndex={-1} className="text-2xl">
          Bonjour {state.firstName}
        </h2>
        <p className="mt-2 text-muted">
          Choisissez le mot de passe de votre Espace ISBREE. Votre identifiant sera{" "}
          <strong className="break-all text-ink">{state.login}</strong>.
          {state.expiresAt ? <> Ce lien est valable jusqu&apos;au {formatDate(state.expiresAt)}.</> : null}
        </p>
      </div>
      {state.error ? (
        <div ref={alertRef} tabIndex={-1} role="alert" className="rounded-xl border border-danger bg-danger-soft p-4 font-semibold text-danger">
          {state.error}
        </div>
      ) : null}
      {/* Helps password managers save the right identifier. */}
      <input type="text" name="username" autoComplete="username" value={state.login} readOnly hidden />
      <div>
        <label htmlFor="password" className="block font-semibold">
          Nouveau mot de passe
        </label>
        <p id="password-hint" className="text-sm text-muted">
          Au moins 10 caractères. Évitez un mot de passe trop simple ou déjà utilisé ailleurs.
        </p>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={10}
          aria-invalid={errors.password ? true : undefined}
          aria-describedby={errors.password ? "password-hint password-error" : "password-hint"}
          className="field mt-1"
        />
        {errors.password ? (
          <p id="password-error" className="mt-1 text-sm font-semibold text-danger">
            {errors.password}
          </p>
        ) : null}
      </div>
      <div>
        <label htmlFor="confirm" className="block font-semibold">
          Confirmer le mot de passe
        </label>
        <input
          id="confirm"
          name="confirm"
          type="password"
          autoComplete="new-password"
          required
          aria-invalid={errors.confirm ? true : undefined}
          aria-describedby={errors.confirm ? "confirm-error" : undefined}
          className="field mt-1"
        />
        {errors.confirm ? (
          <p id="confirm-error" className="mt-1 text-sm font-semibold text-danger">
            {errors.confirm}
          </p>
        ) : null}
      </div>
      <button type="submit" className="btn btn-primary w-full" disabled={pending}>
        {pending ? "Activation…" : "Activer mon compte"}
      </button>
    </form>
  );
}
