import type { Schemas } from "../api/client";
import { describeSla } from "../lib/sla";
import { useNow } from "../lib/useNow";
import { Badge } from "./Badge";

/** A live SLA countdown, coloured by the server's on-track / at-risk / breached status. */
export function SLAChip({
  sla,
  status,
}: {
  sla: Schemas["SLAResponse"] | null;
  status: Schemas["IncidentStatus"];
}) {
  const now = useNow();
  const view = describeSla(sla, status, now);
  return (
    <span data-testid="sla-chip">
      <Badge tone={view.tone}>{view.text}</Badge>
    </span>
  );
}
