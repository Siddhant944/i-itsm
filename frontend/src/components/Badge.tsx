import type { ReactNode } from "react";

import type { Schemas } from "../api/client";
import { priorityLabel, roleLabel, slaLabel, statusLabel } from "../lib/format";

export type Tone = "neutral" | "info" | "good" | "warn" | "bad" | "accent";

const TONE: Record<Tone, string> = {
  neutral: "bg-slate-500/15 text-slate-700 dark:text-slate-300",
  info: "bg-sky-500/15 text-sky-800 dark:text-sky-300",
  good: "bg-emerald-500/15 text-emerald-800 dark:text-emerald-300",
  warn: "bg-amber-500/20 text-amber-800 dark:text-amber-300",
  bad: "bg-red-500/15 text-red-700 dark:text-red-300",
  accent: "bg-accent-soft text-accent-strong",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONE[tone]}`}
    >
      {children}
    </span>
  );
}

const STATUS_TONE: Record<Schemas["IncidentStatus"], Tone> = {
  NEW: "info",
  CLASSIFIED: "info",
  ASSIGNED: "accent",
  ACKNOWLEDGED: "accent",
  IN_PROGRESS: "warn",
  ON_HOLD: "neutral",
  RESOLVED: "good",
  VERIFIED: "good",
  CLOSED: "neutral",
  CANCELLED: "neutral",
};

export function StatusBadge({ status }: { status: Schemas["IncidentStatus"] }) {
  return <Badge tone={STATUS_TONE[status]}>{statusLabel(status)}</Badge>;
}

const PRIORITY_TONE: Record<Schemas["Priority"], Tone> = {
  P1: "bad",
  P2: "warn",
  P3: "info",
  P4: "neutral",
};

export function PriorityBadge({ priority }: { priority: Schemas["Priority"] | null }) {
  if (priority === null) return <Badge>Unprioritised</Badge>;
  return <Badge tone={PRIORITY_TONE[priority]}>{priorityLabel(priority)}</Badge>;
}

const SLA_TONE: Record<Schemas["SLAStatus"], Tone> = {
  on_track: "good",
  at_risk: "warn",
  breached: "bad",
};

export function SLAStatusBadge({ status }: { status: Schemas["SLAStatus"] }) {
  return <Badge tone={SLA_TONE[status]}>{slaLabel(status)}</Badge>;
}

export function RoleBadge({ role }: { role: Schemas["Role"] }) {
  return <Badge tone={role === "employee" ? "neutral" : "accent"}>{roleLabel(role)}</Badge>;
}
