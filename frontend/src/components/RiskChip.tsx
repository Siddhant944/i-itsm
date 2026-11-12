import type { Schemas } from "../api/client";
import { Badge } from "./Badge";

/**
 * §6.3: the predicted chance of missing the resolution target, with the evidence beside it.
 * When there is too little history the 75 % rule answered, and the chip says so.
 */
export function RiskChip({ risk }: { risk: Schemas["RiskResponse"] }) {
  const text =
    risk.probability === null
      ? risk.at_risk
        ? "At risk (75 % rule)"
        : "On track (75 % rule)"
      : `Breach risk ${String(Math.round(risk.probability * 100))}%`;
  return (
    <span data-testid="risk-chip" title={risk.reason}>
      <Badge tone={risk.at_risk ? "warn" : "neutral"}>{text}</Badge>
    </span>
  );
}
