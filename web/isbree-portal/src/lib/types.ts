/** Shapes of the Django APIs read by the portal (portal_api.py, accounts, people, scheduling). */

export type Me = {
  id: string;
  first_name: string;
  last_name: string;
  memberships: { school_code: string; school_name: string; status: string; roles: string[] }[];
};

export type PageSummary = { slug: string; kind: string; title: string; summary: string; to_validate: boolean; is_demo: boolean };
export type Page = PageSummary & { body: string; updated_at: string };
export type Faq = { id: string; category: string; question: string; answer: string; to_validate: boolean; is_demo: boolean };
export type NewsItem = {
  slug: string;
  title: string;
  summary: string;
  body: string;
  category: string;
  event_date: string | null;
  published_at: string | null;
  is_demo: boolean;
};

export type Resource = {
  id: string;
  kind: string;
  title: string;
  body: string;
  level: string | null;
  school_class: string | null;
  academic_year: string | null;
  staff_function: string | null;
  visible_until: string | null;
  has_document: boolean;
  document_name: string;
  document_size: number | null;
  to_validate: boolean;
  is_demo: boolean;
};

export type Release = {
  id: string;
  app: string;
  label: string;
  package: string;
  version_name: string;
  version_code: number;
  release_notes: string;
  min_android: string;
  size: number;
  sha256: string;
  published_at: string | null;
};

export type AppEntry = { app: string; label: string; release: Release | null };

export type PreEnrollmentStatus = {
  reference: string;
  child: string;
  level: string;
  year: string;
  status: string;
  status_label: string;
  message: string;
  submitted_at: string;
};

export type PortalContext = {
  role: string;
  roles: string[];
  user: { first_name: string; last_name: string };
  school: { name: string; phone: string; email: string };
  pages: PageSummary[];
  faq: Faq[];
  news: NewsItem[];
  resources: Resource[];
  apps: AppEntry[];
  pre_enrollments: PreEnrollmentStatus[];
};

export type Child = {
  id: string;
  student: { id: string; first_name: string; last_name: string; student_number: string };
  relationship_type: string;
  enrollment: { class_name: string; academic_year_name: string; status: string } | null;
};

export const RESOURCE_KINDS: Record<string, string> = {
  SUPPLIES: "Fournitures",
  PROGRAMME: "Programme",
  PRACTICAL_INFO: "Informations pratiques",
  CALENDAR: "Calendrier",
  INSTRUCTION: "Consignes",
  PROCEDURE: "Procédure",
  MISSION: "Mission",
  DOCUMENT: "Document",
};

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
