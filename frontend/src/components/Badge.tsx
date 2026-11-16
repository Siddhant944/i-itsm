import type { ReactNode } from "react";

import type { Schemas } from "../api/client";
import { priorityLabel, roleLabel, slaLabel, statusLabel } from "../lib/format";

export type Tone = "neutral" | "info" | "good" | "warn" | "bad" | "accent";

const TONE: Record<Tone, string> = {
  neutral: "bg-neutral-soft text-neutral",
  info: "bg-info-soft text-info",
  good: "bg-good-soft text-good",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
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
