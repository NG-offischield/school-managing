"use server";

import { headers } from "next/headers";

import { publicApiUrl, serverHeaders } from "@/lib/api";
import { clientIp } from "@/lib/client-ip";
import { FIELDS, type Field, type FieldErrors, readForm, type SubmitState, validate } from "@/lib/pre-enrollment";

/**
 * Sends a pre-enrollment request to Django (server to server). Server
 * actions only accept same-origin POSTs (Next checks Origin against Host),
 * which is the CSRF protection of this form. The browser's input is
 * validated again here, then by Django, which alone sets the status, the
 * consent date and the reference. Nothing is stored by this web server.
 */
const NOT_OFFERED = "Ce niveau ou cette année scolaire n'est plus ouvert à la préinscription. Rechargez la page.";

export async function submitPreEnrollment(_previous: SubmitState, form: FormData): Promise<SubmitState> {
  const { values, consent } = readForm(form);
  const honeypot = String(form.get("website") ?? "");
  const checked = validate(values, consent);
  if (!checked.ok) {
    return { status: "invalid", errors: checked.errors, values, message: "Certains champs sont à corriger." };
  }

  const requestHeaders = await headers();
  const ip = clientIp(requestHeaders.get("x-forwarded-for"));
  const { child_birth_date, ...data } = checked.data;
  let response: Response;
  try {
    response = await fetch(publicApiUrl("pre-enrollments/"), {
      method: "POST",
      headers: serverHeaders({
        "Content-Type": "application/json",
        ...(ip ? { "X-ISBREE-Client-IP": ip } : {}),
      }),
      body: JSON.stringify({ ...data, child_birth_date: child_birth_date || null, website: honeypot }),
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    return {
      status: "error",
      values,
      message: "Le service est momentanément indisponible. Votre demande n'a pas été envoyée : réessayez plus tard.",
    };
  }

  if (response.status === 202) {
    const body = (await response.json()) as { data: { reference: string | null } };
    return { status: "received", reference: body.data.reference };
  }
  if (response.status === 429) {
    return {
      status: "error",
      values,
      message: "Trop de demandes ont été envoyées depuis votre connexion. Réessayez dans une heure.",
    };
  }
  if (response.status === 400) {
    const body = (await response.json().catch(() => null)) as {
      error?: { details?: Record<string, unknown> };
    } | null;
    const details = body?.error?.details ?? {};
    const rule = typeof details.rule === "string" ? details.rule : "";
    if (rule === "level_not_offered") {
      return { status: "invalid", errors: { requested_level: NOT_OFFERED }, values, message: NOT_OFFERED };
    }
    const errors: FieldErrors = {};
    for (const field of Object.keys(details)) {
      if ((FIELDS as readonly string[]).includes(field)) {
        errors[field as Field] = "Cette valeur a été refusée par l'établissement. Vérifiez-la.";
      }
    }
    return { status: "invalid", errors, values, message: "Certains champs sont à corriger." };
  }
  return {
    status: "error",
    values,
    message: "Votre demande n'a pas pu être enregistrée. Réessayez plus tard ou contactez l'établissement.",
  };
}
