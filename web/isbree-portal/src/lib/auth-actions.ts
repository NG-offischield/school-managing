"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { visitorIp } from "./dal";
import { NO_RESPONSE, postJson } from "./django";
import {
  DEVICE_COOKIE,
  deviceCookieOptions,
  SESSION_COOKIE,
  sealSession,
  sessionCookieOptions,
  sessionFromTokens,
  type TokenPayload,
  unsealSession,
} from "./session";

/**
 * Login, logout and account activation. Server actions only accept
 * same-origin POSTs (Next checks Origin against Host): that is the CSRF
 * protection of these forms, on top of the SameSite=Lax session cookie.
 */
/** The API did not answer: asleep (free host) or unreachable. */
const WAKING_UP =
  "Le service démarre (hébergement de démonstration en veille) : cela peut prendre jusqu'à une minute. Réessayez dans un instant.";
const UNAVAILABLE = "Le service est momentanément indisponible. Réessayez dans quelques instants.";

function serviceError(status: number) {
  return status === NO_RESPONSE ? WAKING_UP : UNAVAILABLE;
}

export type FormState = { error?: string; fieldErrors?: Record<string, string>; identifier?: string };

export async function login(_previous: FormState, form: FormData): Promise<FormState> {
  const identifier = String(form.get("identifier") ?? "").trim();
  const password = String(form.get("password") ?? "");
  if (!identifier || !password) {
    return {
      identifier,
      error: "Indiquez votre identifiant et votre mot de passe.",
      fieldErrors: {
        ...(identifier ? {} : { identifier: "Indiquez votre identifiant (adresse e-mail ou nom d'utilisateur)." }),
        ...(password ? {} : { password: "Indiquez votre mot de passe." }),
      },
    };
  }
  const store = await cookies();
  // A random identifier per browser (Django hashes it): lets the user recognise the session.
  let device = store.get(DEVICE_COOKIE)?.value;
  if (!device || !/^[0-9a-f-]{36}$/.test(device)) {
    device = crypto.randomUUID();
    store.set(DEVICE_COOKIE, device, deviceCookieOptions());
  }
  const result = await postJson<TokenPayload>(
    "auth/login/",
    {
      identifier,
      password,
      device: { identifier: device, device_name: "Navigateur web", device_type: "BROWSER", platform: "WEB", app_version: "espace-isbree" },
    },
    { clientIp: await visitorIp() },
  );
  if (!result.ok) {
    if (result.status === 401 || result.status === 400) {
      // Same answer whatever the reason: no hint that an account exists.
      return { identifier, error: "Identifiant ou mot de passe incorrect." };
    }
    if (result.status === 429) {
      return { identifier, error: "Trop de tentatives. Patientez une minute avant de réessayer." };
    }
    return { identifier, error: serviceError(result.status) };
  }
  const session = sessionFromTokens(result.data);
  store.set(SESSION_COOKIE, await sealSession(session), sessionCookieOptions(session));
  redirect("/");
}

export async function logout() {
  const store = await cookies();
  const session = await unsealSession(store.get(SESSION_COOKIE)?.value);
  if (session) {
    // Revokes the session in Django: the tokens stop working everywhere.
    await postJson("auth/logout/", {}, { token: session.access, clientIp: await visitorIp() });
  }
  store.delete(SESSION_COOKIE);
  redirect("/connexion?deconnexion=1");
}

// --- account activation (invitation link {portal}/activation#code=…) ---------------------------

export type ActivationState =
  | { step: "code"; error?: string; retryCode?: string }
  | { step: "password"; code: string; firstName: string; login: string; expiresAt: string; error?: string; fieldErrors?: Record<string, string> }
  | { step: "done"; login: string };

const REFUSED =
  "Ce lien d'activation n'est pas valable : il a peut-être expiré (48 heures), déjà été utilisé ou été remplacé. Contactez l'établissement pour en obtenir un nouveau.";

function cleanCode(value: FormDataEntryValue | null) {
  return String(value ?? "").trim().slice(0, 64);
}

export async function checkActivation(_previous: ActivationState, form: FormData): Promise<ActivationState> {
  const code = cleanCode(form.get("code"));
  if (!code) return { step: "code", error: "Le lien d'activation est incomplet. Ouvrez le lien reçu de l'établissement." };
  const result = await postJson<{ first_name: string; login: string; expires_at: string }>(
    "auth/activation/check/",
    { code },
    { clientIp: await visitorIp() },
  );
  if (!result.ok) {
    if (result.status === 429) return { step: "code", error: "Trop de tentatives. Réessayez plus tard." };
    if (result.status === 400) return { step: "code", error: REFUSED };
    // Not an answer about the code: keep it so the person can retry (it left the address bar).
    return { step: "code", error: serviceError(result.status), retryCode: code };
  }
  return { step: "password", code, firstName: result.data.first_name, login: result.data.login, expiresAt: result.data.expires_at };
}

export async function completeActivation(previous: ActivationState, form: FormData): Promise<ActivationState> {
  if (previous.step !== "password") return { step: "code", error: REFUSED };
  const password = String(form.get("password") ?? "");
  const confirm = String(form.get("confirm") ?? "");
  const fieldErrors: Record<string, string> = {};
  if (password.length < 10) fieldErrors.password = "Choisissez un mot de passe d'au moins 10 caractères.";
  else if (password !== confirm) fieldErrors.confirm = "Les deux mots de passe ne correspondent pas.";
  if (Object.keys(fieldErrors).length) return { ...previous, error: "Le mot de passe est à corriger.", fieldErrors };

  const result = await postJson<{ login: string }>(
    "auth/activation/complete/",
    { code: previous.code, password },
    { clientIp: await visitorIp() },
  );
  if (result.ok) return { step: "done", login: result.data.login };
  const details = result.error?.details ?? {};
  if (result.status === 400 && Array.isArray(details.password)) {
    // Django's password rules (too common, too similar to the name…): the code stays usable.
    return {
      ...previous,
      error: "Ce mot de passe n'est pas accepté.",
      fieldErrors: { password: "Mot de passe trop simple ou trop proche de vos informations personnelles. Choisissez-en un autre." },
    };
  }
  if (result.status === 429) return { ...previous, error: "Trop de tentatives. Réessayez plus tard." };
  if (result.status === 400) return { step: "code", error: REFUSED };
  return { ...previous, error: serviceError(result.status) }; // the code may still be valid: retry possible
}
