/**
 * The application's clock, as far as the browser can know it.
 *
 * SLA deadlines are measured on the server's injected Clock, which runs ×10 in the demo and
 * stands still in tests, so a countdown based on the browser's own clock would be wrong. Every
 * API response carries the server's time and how fast its clock runs; we extrapolate from the
 * most recent one.
 */
interface Sync {
  serverMs: number;
  localMs: number;
  rate: number;
}

let last: Sync | null = null;

export function syncServerTime(serverIso: string | null, rate: string | null): void {
  if (serverIso === null) return;
  const serverMs = Date.parse(serverIso);
  if (Number.isNaN(serverMs)) return;
  const parsedRate = rate === null ? 1 : Number(rate);
  last = {
    serverMs,
    localMs: Date.now(),
    rate: Number.isFinite(parsedRate) && parsedRate >= 0 ? parsedRate : 1,
  };
}

/** The current time on the application's clock, in milliseconds since the epoch. */
export function serverNow(): number {
  if (last === null) return Date.now();
  return last.serverMs + (Date.now() - last.localMs) * last.rate;
}

/** Test helper: forget what the server said. */
export function resetServerTime(): void {
  last = null;
}
