import type { Schemas } from "../../api/client";
import type { Incident } from "../../api/hooks";
import type { Me } from "../../auth/portal";

type Status = Schemas["IncidentStatus"];

/** What the signed-in person can do to this incident right now. */
export interface Available {
  acknowledge: boolean;
  start: boolean;
  resume: boolean;
  note: boolean;
  requestInformation: boolean;
  resolve: boolean;
  close: boolean;
  reassign: boolean;
  overridePriority: boolean;
  overrideCategory: boolean;
  provideInformation: boolean;
  verify: boolean;
  cancel: boolean;
}

const OPEN: readonly Status[] = [
  "NEW",
  "CLASSIFIED",
  "ASSIGNED",
  "ACKNOWLEDGED",
  "IN_PROGRESS",
  "ON_HOLD",
];
const WORKABLE: readonly Status[] = ["ASSIGNED", "ACKNOWLEDGED", "IN_PROGRESS", "ON_HOLD"];
const REASSIGNABLE: readonly Status[] = ["CLASSIFIED", "ASSIGNED", "ACKNOWLEDGED", "IN_PROGRESS"];

/**
 * Which buttons to offer, from the §4 lifecycle and the caller's permissions.
 *
 * This only decides what is *shown*: the API checks the role, the ownership (BR-01, BR-02) and
 * the transition again, and its refusal is what the user sees if the two ever disagree.
 */
export function availableActions(
  incident: Incident,
  me: Me,
  teamMemberIds: readonly number[] = [],
): Available {
  const can = (permission: Schemas["Permission"]) => me.permissions.includes(permission);
  const { status } = incident;
  const isReporter = incident.reporter_id === me.id;
  const isAssignee = incident.assignee_id === me.id;
  const open = OPEN.includes(status);
  // Nobody holds it yet: "queued for the Team Lead" (§5.3, D-028).
  const waiting = incident.assignee_id === null && (status === "NEW" || status === "CLASSIFIED");
  // BR-02, as the API applies it: the assignee, an admin, or a Team Lead for their own team's
  // incidents and for the ones still waiting for anybody.
  const leads =
    can("incident:reassign") &&
    (waiting || (incident.assignee_id !== null && teamMemberIds.includes(incident.assignee_id)));
  const works = can("incident:work") && (isAssignee || can("incident:view_all") || leads);

  return {
    acknowledge: works && status === "ASSIGNED",
    start: works && status === "ACKNOWLEDGED",
    resume: works && status === "ON_HOLD",
    note: works && WORKABLE.includes(status),
    requestInformation: works && status === "IN_PROGRESS",
    resolve: works && status === "IN_PROGRESS",
    close: works && status === "VERIFIED",
    reassign: can("incident:reassign") && works && REASSIGNABLE.includes(status),
    overridePriority: can("incident:override_priority") && works && open,
    overrideCategory: can("incident:override_category") && works && open,
    provideInformation: isReporter && can("incident:add_info") && open,
    verify: isReporter && can("incident:verify") && status === "RESOLVED",
    cancel: open && ((isReporter && can("incident:cancel_own")) || can("incident:cancel_any")),
  };
}

export interface TimelineEntry {
  at: string;
  title: string;
  body?: string | undefined;
  actorId?: number | undefined;
  kind: "event" | "note" | "question" | "answer";
}

/** The incident's story in order, built from what the API already returns. */
export function timelineOf(incident: Incident): TimelineEntry[] {
  const entries: TimelineEntry[] = [
    { at: incident.created_at, title: "Reported", actorId: incident.reporter_id, kind: "event" },
  ];
  if (incident.acknowledged_at !== null) {
    entries.push({ at: incident.acknowledged_at, title: "Acknowledged", kind: "event" });
  }
  for (const note of incident.notes) {
    const shape =
      note.kind === "info_request"
        ? ({ title: "Information requested", kind: "question" } as const)
        : note.kind === "info_response"
          ? ({ title: "Information provided", kind: "answer" } as const)
          : ({ title: "Work note", kind: "note" } as const);
    entries.push({ at: note.created_at, body: note.text, actorId: note.author_id, ...shape });
  }
  if (incident.resolution !== null) {
    entries.push({
      at: incident.resolution.resolved_at,
      title: "Resolved",
      body: incident.resolution.summary,
      actorId: incident.resolution.resolver_id,
      kind: "event",
    });
  }
  if (incident.feedback !== null) {
    entries.push({
      at: incident.feedback.given_at,
      title: `Fix verified · rated ${String(incident.feedback.rating)}/5`,
      body: incident.feedback.comment === "" ? undefined : incident.feedback.comment,
      actorId: incident.reporter_id,
      kind: "event",
    });
  }
  if (incident.closed_at !== null) {
    entries.push({
      at: incident.closed_at,
      title: incident.status === "CANCELLED" ? "Cancelled" : "Closed",
      kind: "event",
    });
  }
  // A stable sort keeps same-instant entries in the order they were built.
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => Date.parse(a.entry.at) - Date.parse(b.entry.at) || a.index - b.index)
    .map(({ entry }) => entry);
}

/** The latest question the reporter has not yet answered, if the incident is waiting on them. */
export function pendingQuestion(incident: Incident): string | null {
  if (incident.status !== "ON_HOLD") return null;
  const last = [...incident.notes].reverse().find((note) => note.kind !== "note");
  return last?.kind === "info_request" ? last.text : null;
}
