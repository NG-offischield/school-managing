"use client";

import { useActionState, useEffect, useRef } from "react";

import { type FormState, login } from "@/lib/auth-actions";

export function LoginForm({ action = login }: { action?: typeof login }) {
  const [state, formAction, pending] = useActionState(action, {} as FormState);
  const alertRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (state.error) alertRef.current?.focus();
  }, [state]);
  const errors = state.fieldErrors ?? {};
  return (
    <form action={formAction} className="space-y-5" noValidate>
      {state.error ? (
        <div ref={alertRef} tabIndex={-1} role="alert" className="rounded-xl border border-danger bg-danger-soft p-4 font-semibold text-danger">
          {state.error}
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
      <button type="submit" className="btn btn-primary w-full" disabled={pending}>
        {pending ? "Connexion…" : "Se connecter"}
      </button>
    </form>
  );
}
