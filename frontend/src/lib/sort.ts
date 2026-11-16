import type { IncidentSummary } from "../api/hooks";

const RANK: Record<string, number> = { P1: 0, P2: 1, P3: 2, P4: 3 };
const DONE = new Set(["RESOLVED", "VERIFIED", "CLOSED", "CANCELLED"]);
/**
 * Nothing left for the technician to do. RESOLVED is not here: it waits on the reporter and can
 * come back as IN_PROGRESS (§4), so it stays in a queue, as it does in the team queue.
 */
const FINISHED = new Set(["VERIFIED", "CLOSED", "CANCELLED"]);

/** Most urgent first: open work before finished work, then priority, then age. */
export function byUrgency(a: IncidentSummary, b: IncidentSummary): number {
  return (
    Number(DONE.has(a.status)) - Number(DONE.has(b.status)) ||
    (RANK[a.priority ?? ""] ?? 9) - (RANK[b.priority ?? ""] ?? 9) ||
    Date.parse(a.created_at) - Date.parse(b.created_at)
  );
}

export function isFinished(incident: Pick<IncidentSummary, "status">): boolean {
  return FINISHED.has(incident.status);
}
