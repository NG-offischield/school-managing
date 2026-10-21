"use client";

import { type FormEvent, startTransition, useActionState, useEffect, useRef, useState } from "react";

import { type FormState, login } from "@/lib/auth-actions";
import { waitForApi } from "@/lib/wait-for-api";

/** "checking": first readiness check; "waking": the API is starting; "timeout": it did not start in time. */
type Phase = "idle" | "checking" | "waking" | "timeout";

const NOT_RESPONDING =
  "Le serveur ne répond pas actuellement. Vos informations sont conservées : réessayez dans un instant.";

/**
 * Sign-in in two steps: the form first waits for the API to be ready (free
 * host asleep: about a minute), repeating only an anonymous readiness check,
 * then sends the credentials ONCE. The fields are kept while waiting and
 * after a timeout (the form is not reset); the password stays in the field,
 * never stored elsewhere.
 */
export function LoginForm({ action = login, wait = waitForApi }: { action?: typeof login; wait?: typeof waitForApi }) {
  const [state, formAction, pending] = useActionState(action, {} as FormState);
  const [phase, setPhase] = useState<Phase>("idle");
  const alertRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const busy = pending || phase === "checking" || phase === "waking";

  useEffect(() => {
    if (state.error) alertRef.current?.focus();
  }, [state]);
  useEffect(() => {
    if (phase === "timeout") alertRef.current?.focus();
  }, [phase]);
  useEffect(() => () => abortRef.current?.abort(), []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    // Missing fields are reported by the action at once: no need to wait for the API.
    if (String(data.get("identifier") ?? "").trim() && String(data.get("password") ?? "")) {
      abortRef.current = new AbortController();
      setPhase("checking");
      const readiness = await wait({ signal: abortRef.current.signal, onWaiting: () => setPhase("waking") });
      if (readiness !== "ready") {
        setPhase(readiness === "timeout" ? "timeout" : "idle");
        return;
      }
    }
    setPhase("idle");
    startTransition(() => formAction(data));
  }

  const error = phase === "timeout" ? NOT_RESPONDING : busy ? undefined : state.error;
  const errors = busy ? {} : (state.fieldErrors ?? {});
  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate aria-busy={busy}>
      {error ? (
        <div ref={alertRef} tabIndex={-1} role="alert" className="rounded-xl border border-danger bg-danger-soft p-4 font-semibold text-danger">
          {error}
        </div>
      ) : null}
      <div>
        <label htmlFor="identifier" className="block font-semibold">
          Identifiant
        </label>
        <p id="identifier-hint" className="text-sm text-muted">
          Votre adresse e-mail ou votre nom d&apos;utilisateur.
        </p>
        <input
          id="identifier"
          name="identifier"
          type="text"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
          defaultValue={state.identifier ?? ""}
          aria-invalid={errors.identifier ? true : undefined}
          aria-describedby={errors.identifier ? "identifier-hint identifier-error" : "identifier-hint"}
          className="field mt-1"
        />
        {errors.identifier ? (
          <p id="identifier-error" className="mt-1 text-sm font-semibold text-danger">
            {errors.identifier}
          </p>
        ) : null}
      </div>
      <div>
        <label htmlFor="password" className="block font-semibold">
          Mot de passe
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          aria-invalid={errors.password ? true : undefined}
          aria-describedby={errors.password ? "password-error" : undefined}
          className="field mt-1"
        />
        {errors.password ? (
          <p id="password-error" className="mt-1 text-sm font-semibold text-danger">
            {errors.password}
          </p>
        ) : null}
      </div>
      <button type="submit" className="btn btn-primary w-full" disabled={busy}>
        {busy ? "Connexion…" : phase === "timeout" ? "Réessayer" : "Se connecter"}
      </button>
      <p className="text-sm text-muted" role="status" aria-live="polite">
        {phase === "waking"
          ? "Connexion au serveur… Le premier démarrage peut prendre un moment (environ une minute) : la connexion continuera automatiquement."
          : busy
            ? "Connexion au serveur…"
            : ""}
      </p>
    </form>
  );
}
