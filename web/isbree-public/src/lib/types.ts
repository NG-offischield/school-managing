/** Shapes of the public Django API (apps/website/public_api.py). */

export type Editorial = { to_validate?: boolean; is_demo: boolean };

export type Level = { id: string; code: string; name: string; cycle: string };
export type Year = { id: string; name: string };
export type Choice = { value: string; label: string };

export type SiteLocation = {
  id: string;
  name: string;
  description: string;
  address_text: string;
  is_main: boolean;
  is_demo: boolean;
};

export type Site = {
  school: {
    code: string;
    name: string;
    short_name: string;
    city: string;
    country: string;
    phone: string;
    email: string;
  };
  profile: {
    tagline: string;
    presentation: string;
    values: string[];
    pedagogy: string;
    location_details: string;
    address: string;
    address_confirmed: boolean;
    office_hours: string;
    to_validate: boolean;
  };
  locations: SiteLocation[];
  levels: Level[];
  years: Year[];
  relationships: Choice[];
};

export type PageSummary = Editorial & {
  slug: string;
  kind: string;
  title: string;
  summary: string;
};

export type Page = PageSummary & { body: string; updated_at: string };

export type Faq = Editorial & { id: string; category: string; question: string; answer: string };

export type ImageRef = {
  id: string;
  width: number | null;
  height: number | null;
  alt_text: string;
  caption: string;
  credit: string;
  category: string;
  is_illustration: boolean;
  is_demo: boolean;
};

export type NewsSummary = {
  slug: string;
  title: string;
  summary: string;
  category: string;
  event_date: string | null;
  published_at: string | null;
  cover: ImageRef | null;
  is_demo: boolean;
};

export type News = NewsSummary & { body: string };

export const FAQ_CATEGORIES: Record<string, string> = {
  ADMISSIONS: "Admissions",
  PREENROLLMENT: "Préinscription",
  ORGANIZATION: "Organisation scolaire",
  DOCUMENTS: "Documents",
  ACTIVATION: "Activation du compte",
  PORTAL: "Espace ISBREE",
  CONTACT: "Contacts",
  PRACTICAL: "Informations pratiques",
  TEACHING: "Enseignement",
  WORK: "Vie professionnelle",
};

export const NEWS_CATEGORIES: Record<string, string> = {
  NEWS: "Actualité",
  EVENT: "Événement",
  SCHOOL_LIFE: "Vie scolaire",
  ANNOUNCEMENT: "Annonce",
};

export const IMAGE_CATEGORIES: Record<string, string> = {
  CLASSROOMS: "Salles de classe",
  CAMPUS: "Établissement",
  SPORTS: "Sport",
  ACTIVITIES: "Activités",
  EVENTS: "Événements",
  OTHER: "Autre",
};

/** Legal / information pages linked from the footer, by kind, with their route. */
export const INFO_PAGES: { kind: string; label: string }[] = [
  { kind: "LEGAL_NOTICE", label: "Mentions légales" },
  { kind: "PRIVACY", label: "Confidentialité" },
  { kind: "TERMS", label: "Conditions d'utilisation" },
  { kind: "RULES", label: "Règlement intérieur" },
];
