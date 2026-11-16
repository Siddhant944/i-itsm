import type { Schemas } from "../api/client";
import type { Tone } from "../components/Badge";
import { formatDuration } from "./format";

type SLA = Schemas["SLAResponse"];
type Status = Schemas["IncidentStatus"];

const TONE: Record<Schemas["SLAStatus"], Tone> = {
  on_track: "good",
  at_risk: "warn",
  breached: "bad",
};

/** The clock has stopped for good once the fix is in (blueprint §4: SLA effects). */
const STOPPED: readonly Status[] = ["RESOLVED", "VERIFIED", "CLOSED", "CANCELLED"];

export interface SLAView {
  tone: Tone;
  text: string;
}

/** What the chip says, separated from the component so it can be tested without timers. */
export function describeSla(sla: SLA | null, status: Status, now: number): SLAView {
  if (sla === null) return { tone: "neutral", text: "No SLA yet" };
  // A cancelled incident was never resolved, so its SLA was neither met nor missed.
  if (status === "CANCELLED") return { tone: "neutral", text: "SLA stopped" };
  if (STOPPED.includes(status)) {
    // "Met" means both halves: a fast fix does not undo a late first response.
    return sla.resolution_status === "breached" || sla.response_status === "breached"
      ? { tone: "bad", text: "SLA breached" }
      : { tone: "good", text: "SLA met" };
  }
  if (sla.paused) return { tone: "neutral", text: "SLA paused" };

  const awaitingResponse = sla.responded_at === null;
  const phase = awaitingResponse ? "Response" : "Resolution";
  const deadline = Date.parse(awaitingResponse ? sla.response_deadline : sla.resolution_deadline);
  const state = awaitingResponse ? sla.response_status : sla.resolution_status;
  const remaining = deadline - now;
  // "Breached iff now > deadline" (BR-07): the server's status wins over our extrapolated clock.
  if (state === "breached" || remaining < 0) {
    return { tone: "bad", text: `${phase} overdue by ${formatDuration(remaining)}` };
  }
  return { tone: TONE[state], text: `${phase} due in ${formatDuration(remaining)}` };
}

/**
 * When the running SLA clock runs out, for sorting by "SLA due": the response deadline until the
 * first response, then the resolution deadline. Null when no clock is running (no SLA yet,
 * paused, or stopped), so those incidents sort after every running one.
 */
export function slaDueAt(sla: SLA | null, status: Status): number | null {
  if (sla === null || sla.paused || STOPPED.includes(status)) return null;
  return Date.parse(sla.responded_at === null ? sla.response_deadline : sla.resolution_deadline);
}
