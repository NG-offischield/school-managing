/** The four portal roles (Django RoleCode) and how the portal names them. */
export const ROLES = {
  PARENT: { slug: "parent", label: "Parent", space: "Espace Parent" },
  TEACHER: { slug: "enseignant", label: "Enseignant", space: "Espace Enseignant" },
  STAFF: { slug: "personnel", label: "Personnel", space: "Espace Personnel" },
  GUARDIAN: { slug: "gardien", label: "Gardien", space: "Espace Gardien" },
} as const;

export type Role = keyof typeof ROLES;
export const PORTAL_ROLES = Object.keys(ROLES) as Role[];

export function roleFromSlug(slug: string): Role | null {
  return PORTAL_ROLES.find((role) => ROLES[role].slug === slug) ?? null;
}

/** The portal roles a user holds in the school, in a stable order. */
export function portalRoles(roles: string[]): Role[] {
  return PORTAL_ROLES.filter((role) => roles.includes(role));
}

export function spaceHref(role: Role) {
  return `/espace/${ROLES[role].slug}`;
}
