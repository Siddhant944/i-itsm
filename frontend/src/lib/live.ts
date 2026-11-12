import { useSyncExternalStore } from "react";

/** P4.8: whether the live-update socket is connected, shared by the hook and the banner. */
export type LiveState = "off" | "connecting" | "live" | "reconnecting";

let state: LiveState = "off";
const listeners = new Set<() => void>();

export function setLiveState(next: LiveState): void {
  if (next === state) return;
  state = next;
  for (const listener of listeners) listener();
}

export function liveState(): LiveState {
  return state;
}

export function useLiveState(): LiveState {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => state,
  );
}

/** Polling while pushes arrive is only a safety net (D-024 replaced by P4.8). */
export const POLL_MS = 10_000;
export const POLL_WHEN_LIVE_MS = 60_000;

/** The refetch interval for live screens: slow while the socket is up, quick otherwise. */
export function liveInterval(): number {
  return state === "live" ? POLL_WHEN_LIVE_MS : POLL_MS;
}
