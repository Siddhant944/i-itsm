import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { getToken } from "../lib/session";
import { setLiveState } from "../lib/live";
import { apiBaseUrl } from "./client";

const FIRST_RETRY_MS = 1_000;
const MAX_RETRY_MS = 30_000;

/** The socket's URL: the API's own, with ws(s) for http(s). */
export function liveUrl(base: string = apiBaseUrl): string {
  return `${base.replace(/^http/, "ws").replace(/\/$/, "")}/ws`;
}

interface Push {
  type: string;
  incident_id?: string;
}

/** A push says only *what* changed; the data is refetched through the API (BR-01). */
export function applyPush(client: QueryClient, push: Push): void {
  if (push.type !== "incident" || push.incident_id === undefined) return;
  void client.invalidateQueries({ queryKey: ["incident", push.incident_id] });
  for (const key of ["incidents", "notifications", "workload", "violations", "dashboard"]) {
    void client.invalidateQueries({ queryKey: [key] });
  }
}

/**
 * P4.8: keep a WebSocket open while signed in and refetch what a push says has changed.
 * It reconnects with backoff (1 s doubling to 30 s); while it is down, screens poll as before.
 */
export function useLive(enabled = true): void {
  const client = useQueryClient();
  useEffect(() => {
    if (!enabled || typeof WebSocket === "undefined") return;
    let socket: WebSocket | null = null;
    let retry = FIRST_RETRY_MS;
    let timer: number | undefined;
    let stopped = false;

    const connect = () => {
      const token = getToken();
      if (token === null) {
        setLiveState("off");
        return;
      }
      setLiveState(retry === FIRST_RETRY_MS ? "connecting" : "reconnecting");
      socket = new WebSocket(liveUrl());
      socket.onopen = () => {
        socket?.send(JSON.stringify({ token }));
      };
      socket.onmessage = (event: MessageEvent<string>) => {
        const push = JSON.parse(event.data) as Push;
        if (push.type === "ready") {
          retry = FIRST_RETRY_MS;
          setLiveState("live");
          return;
        }
        applyPush(client, push);
      };
      socket.onclose = (event: CloseEvent) => {
        if (stopped) return;
        // 4401: the token is no longer good; the next API call signs the user out.
        if (event.code === 4401) {
          setLiveState("off");
          return;
        }
        setLiveState("reconnecting");
        timer = window.setTimeout(connect, retry);
        retry = Math.min(retry * 2, MAX_RETRY_MS);
      };
    };

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      socket?.close();
      setLiveState("off");
    };
  }, [client, enabled]);
}
