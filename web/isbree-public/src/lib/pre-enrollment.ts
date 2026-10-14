import { z } from "zod";

/**
 * Pre-enrollment form rules, shared by the browser (immediate feedback) and
 * the server action (the browser is never trusted). Django validates again
 * and alone decides the status, the consent date and the reference.
 * Same limits as apps/website/public_api.py::PreEnrollmentInput.
 */
const PHONE = /^\+?[0-9 ()./-]{6,25}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const name = (label: string) =>
  z
    .string()
    .trim()
    .min(1, `Indiquez ${label}.`)
    .max(100, `${label.charAt(0).toUpperCase()}${label.slice(1)} : 100 caractères au maximum.`);

export const FIELDS = [
  "guardian_first_name",
  "guardian_last_name",
  "guardian_phone",
  "guardian_email",
  "relationship",
  "child_first_name",
  "child_last_name",
  "child_birth_date",
  "requested_level",
  "requested_year",
  "previous_school",
  "comment",
  "consent",
] as const;

export type Field = (typeof FIELDS)[number];

export function plausibleBirthDate(value: string, today = new Date()) {
  if (!value) return true;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T12:00:00Z`);
  if (Number.isNaN(date.getTime())) return false;
  const year = date.getUTCFullYear();
  return year >= today.getFullYear() - 30 && date <= today;
}

export const preEnrollmentSchema = z.object({
  guardian_first_name: name("le prénom du responsable"),
  guardian_last_name: name("le nom du responsable"),
  guardian_phone: z
    .string()
    .trim()
    .regex(PHONE, "Indiquez un numéro de téléphone valide (chiffres, espaces, + au début)."),
  guardian_email: z.string().trim().max(254).email("Indiquez une adresse e-mail valide."),
  relationship: z.string().min(1, "Indiquez votre lien avec l'enfant."),
  child_first_name: name("le prénom de l'enfant"),
  child_last_name: name("le nom de l'enfant"),
  child_birth_date: z
    .string()
    .trim()
    .refine((v) => plausibleBirthDate(v), "Indiquez une date de naissance plausible."),
  requested_level: z.string().regex(UUID, "Choisissez le niveau demandé."),
  requested_year: z.string().regex(UUID, "Choisissez l'année scolaire."),
  previous_school: z.string().trim().max(200, "200 caractères au maximum."),
  comment: z.string().trim().max(1000, "Votre message : 1000 caractères au maximum."),
  consent: z.literal(true, { error: "Vous devez accepter l'utilisation de vos données pour traiter la demande." }),
});

export type PreEnrollment = z.infer<typeof preEnrollmentSchema>;
export type FieldErrors = Partial<Record<Field, string>>;
export type Values = Partial<Record<Field, string>>;

/** Reads the form into plain strings (the honeypot is read separately). */
export function readForm(form: FormData) {
  const values: Values = {};
  for (const field of FIELDS) {
    if (field === "consent") continue;
    const value = form.get(field);
    values[field] = typeof value === "string" ? value : "";
  }
  return { values, consent: form.get("consent") === "on" };
}

export function validate(values: Values, consent: boolean):
  | { ok: true; data: PreEnrollment }
  | { ok: false; errors: FieldErrors } {
  const parsed = preEnrollmentSchema.safeParse({ ...values, consent });
  if (parsed.success) return { ok: true, data: parsed.data };
  const errors: FieldErrors = {};
  for (const issue of parsed.error.issues) {
    const field = issue.path[0] as Field;
    if (field && !errors[field]) errors[field] = issue.message;
  }
  return { ok: false, errors };
}

export const FIELD_LABELS: Record<Field, string> = {
  guardian_first_name: "Prénom du responsable",
  guardian_last_name: "Nom du responsable",
  guardian_phone: "Téléphone",
  guardian_email: "Adresse e-mail",
  relationship: "Lien avec l'enfant",
  child_first_name: "Prénom de l'enfant",
  child_last_name: "Nom de l'enfant",
  child_birth_date: "Date de naissance",
  requested_level: "Niveau demandé",
  requested_year: "Année scolaire",
  previous_school: "Établissement actuel",
  comment: "Message",
  consent: "Consentement",
};

export type SubmitState =
  | { status: "idle" }
  | { status: "invalid"; errors: FieldErrors; values: Values; message: string }
  | { status: "error"; values: Values; message: string }
  | { status: "received"; reference: string | null };
