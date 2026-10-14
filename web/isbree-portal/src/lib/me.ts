import "server-only";

import { cache } from "react";

import { config } from "./config";
import { api } from "./dal";
import { portalRoles, type Role } from "./roles";
import type { Me } from "./types";

/** The current user and the portal roles held in THIS school (from Django, never from the client). */
export const getMe = cache(async (): Promise<{ name: string; roles: Role[] } | null> => {
  const me = await api<Me>("auth/me/");
  if (!me.ok) return null;
  const membership = me.data.memberships.find((m) => m.school_code === config.schoolCode && m.status === "ACTIVE");
  return {
    name: `${me.data.first_name} ${me.data.last_name}`.trim(),
    roles: membership ? portalRoles(membership.roles) : [],
  };
});
