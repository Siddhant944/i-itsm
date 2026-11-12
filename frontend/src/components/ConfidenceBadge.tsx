import { confidenceBand } from "../lib/confidence";
import { Badge } from "./Badge";

/** An AI suggestion's confidence, as a band and a percentage. */
export function ConfidenceBadge({ confidence }: { confidence: number }) {
  const clamped = Math.min(1, Math.max(0, confidence));
  const band = confidenceBand(clamped);
  return (
    <Badge tone={band.tone}>
      {band.label} · {String(Math.round(clamped * 100))}%
    </Badge>
  );
}
