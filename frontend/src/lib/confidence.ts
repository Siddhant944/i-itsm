import type { Tone } from "../components/Badge";

/**
 * How sure an AI suggestion is (AGENTS.md: suggestions show their confidence).
 * The bands are deliberately coarse: a number alone invites false precision.
 */
export function confidenceBand(confidence: number): { label: string; tone: Tone } {
  if (confidence >= 0.75) return { label: "High confidence", tone: "good" };
  if (confidence >= 0.45) return { label: "Medium confidence", tone: "warn" };
  return { label: "Low confidence", tone: "neutral" };
}
