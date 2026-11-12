/** Display helpers. Times are stored in UTC and shown in IST (AGENTS.md: Time). */
import type { Schemas } from "../api/client";

const IST_DATE_TIME = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const IST_DAY = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "2-digit",
  month: "short",
});

export function formatDateTime(iso: string | null | undefined): string {
  if (iso === null || iso === undefined) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : `${IST_DATE_TIME.format(date)} IST`;
}

export function formatDay(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : IST_DAY.format(date);
}

/** "4m 12s", "2h 05m", "3d 4h" — the largest two units that matter. */
export function formatDuration(milliseconds: number): string {
  const total = Math.max(0, Math.floor(Math.abs(milliseconds) / 1000));
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const two = (value: number) => String(value).padStart(2, "0");
  if (days > 0) return `${String(days)}d ${String(hours)}h`;
  if (hours > 0) return `${String(hours)}h ${two(minutes)}m`;
  if (minutes > 0) return `${String(minutes)}m ${two(seconds)}s`;
  return `${String(seconds)}s`;
}

export function formatHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return "—";
  if (hours < 1) return `${String(Math.round(hours * 60))} min`;
  return `${hours.toFixed(1)} h`;
}

/** The API already sends shares as percentages (23.7 means 23.7%). */
export function formatPercent(percentage: number | null | undefined): string {
  if (percentage === null || percentage === undefined) return "—";
  return `${String(Math.round(percentage * 10) / 10)}%`;
}

export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${String(minutes)} min`;
  const hours = minutes / 60;
  return Number.isInteger(hours) ? `${String(hours)} h` : `${hours.toFixed(1)} h`;
}

const STATUS_LABEL: Record<Schemas["IncidentStatus"], string> = {
  NEW: "New",
  CLASSIFIED: "Classified",
  ASSIGNED: "Assigned",
  ACKNOWLEDGED: "Acknowledged",
  IN_PROGRESS: "In progress",
  ON_HOLD: "On hold",
  RESOLVED: "Resolved",
  VERIFIED: "Verified",
  CLOSED: "Closed",
  CANCELLED: "Cancelled",
};

export const ALL_STATUSES = Object.keys(STATUS_LABEL) as Schemas["IncidentStatus"][];
export const ALL_PRIORITIES: Schemas["Priority"][] = ["P1", "P2", "P3", "P4"];
export const ALL_SLA_STATUSES: Schemas["SLAStatus"][] = ["on_track", "at_risk", "breached"];
export const ALL_TIERS: Schemas["SLATier"][] = ["gold", "silver", "bronze"];
export const ALL_ROLES: Schemas["Role"][] = [
  "employee",
  "technician",
  "team_lead",
  "administrator",
  "it_manager",
];

export function statusLabel(status: Schemas["IncidentStatus"]): string {
  return STATUS_LABEL[status];
}

const PRIORITY_LABEL: Record<Schemas["Priority"], string> = {
  P1: "P1 Critical",
  P2: "P2 High",
  P3: "P3 Medium",
  P4: "P4 Low",
};

export function priorityLabel(priority: Schemas["Priority"]): string {
  return PRIORITY_LABEL[priority];
}

const SLA_LABEL: Record<Schemas["SLAStatus"], string> = {
  on_track: "On track",
  at_risk: "At risk",
  breached: "Breached",
};

export function slaLabel(status: Schemas["SLAStatus"]): string {
  return SLA_LABEL[status];
}

const ROLE_LABEL: Record<Schemas["Role"], string> = {
  employee: "Employee",
  technician: "Technician",
  team_lead: "Team Lead",
  administrator: "Administrator",
  it_manager: "IT Manager",
};

export function roleLabel(role: Schemas["Role"]): string {
  return ROLE_LABEL[role];
}

/** "load_based" → "Load based". */
export function titleCase(value: string): string {
  const spaced = value.replace(/[_.:]/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const LEVELS = ["Low", "Medium", "High"] as const;

/** Impact, urgency and criticality are all 1-3 (blueprint §5.1). */
export function levelLabel(level: number): string {
  return LEVELS[level - 1] ?? String(level);
}

/** "wifi, Network ,," → ["wifi", "Network"]; the API lower-cases and de-duplicates. */
export function parseKeywords(text: string): string[] {
  return text
    .split(",")
    .map((word) => word.trim())
    .filter((word) => word !== "");
}
