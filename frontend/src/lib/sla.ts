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
  if (STOPPED.includes(status)) {
    return sla.resolution_status === "breached"
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
