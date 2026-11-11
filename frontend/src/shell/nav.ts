import type { Schemas } from "../api/client";
import type { Portal } from "../auth/portal";

export interface NavItem {
  label: string;
  to: string;
  /** Shown only when the signed-in role holds this permission. */
  permission?: Schemas["Permission"] | undefined;
  group?: string | undefined;
}

/**
 * Every screen of every portal, in one place. The shell renders these as navigation and the
 * router test walks them, so a screen cannot exist without a link to it (AGENTS.md: Frontend).
 */
export const NAVIGATION: Record<Portal, readonly NavItem[]> = {
  employee: [
    { label: "My incidents", to: "/employee/incidents" },
    { label: "Report an incident", to: "/employee/report" },
  ],
  technician: [
    { label: "My queue", to: "/technician/queue" },
    { label: "Team queue", to: "/technician/team", permission: "incident:view_team" },
    { label: "Workload", to: "/technician/workload" },
    { label: "Report an incident", to: "/technician/report" },
    // Only the reporter can confirm a fix (BR-03), so staff need a way back to what they reported.
    { label: "My reports", to: "/technician/reports" },
  ],
  admin: [
    { label: "Dashboard", to: "/admin/dashboard", group: "Operations" },
    { label: "Incidents", to: "/admin/incidents", group: "Operations" },
    { label: "SLA violations", to: "/admin/violations", group: "Operations" },
    { label: "Audit log", to: "/admin/audit", group: "Operations" },
    { label: "Users", to: "/admin/users", group: "Operations" },
    { label: "Categories", to: "/admin/config/categories", group: "Configuration" },
    { label: "Services", to: "/admin/config/services", group: "Configuration" },
    { label: "SLA policies", to: "/admin/config/sla", group: "Configuration" },
    { label: "Assignment", to: "/admin/config/assignment", group: "Configuration" },
  ],
};

export const PORTAL_HOME: Record<Portal, string> = {
  employee: "/employee/incidents",
  technician: "/technician/queue",
  admin: "/admin/dashboard",
};

export const PORTAL_TITLE: Record<Portal, string> = {
  employee: "Help Desk",
  technician: "Technician Console",
  admin: "Service Management",
};

/** Where one incident opens inside the caller's own portal. */
export function incidentPath(portal: Portal, id: string): string {
  return `/${portal}/incidents/${id}`;
}
