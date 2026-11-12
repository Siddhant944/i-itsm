import type { Schemas } from "../api/client";

export type Me = Schemas["MeResponse"];
export type Portal = "employee" | "technician" | "admin";

/** Narrow the API's portal string to the three we render. */
export function portalOf(user: Me): Portal {
  return user.portal === "technician" || user.portal === "admin" ? user.portal : "employee";
}
