import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { liveInterval, liveState, POLL_MS, POLL_WHEN_LIVE_MS } from "../lib/live";
import { setToken } from "../lib/session";
import { LiveBanner } from "../shell/PortalShell";
import { applyPush, liveUrl, useLive } from "./useLive";

/** A stand-in for the browser's WebSocket that the test drives by hand. */
class FakeSocket {
  static opened: FakeSocket[] = [];
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.opened.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.onclose?.({ code: 1000 });
  }
  open() {
    this.onopen?.();
  }
  push(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
  drop(code = 1006) {
    this.onclose?.({ code });
  }
}

function Harness({ children }: { children?: ReactNode }) {
  useLive(true);
  return (
    <>
      <LiveBanner />
      {children}
    </>
  );
}

function mount(client = new QueryClient()) {
  render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
  return client;
}

describe("live updates (P4.8)", () => {
  beforeEach(() => {
    FakeSocket.opened = [];
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.useFakeTimers();
    setToken("token-1");
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    setToken(null);
  });

  it("signs in with the first message, then refetches what a push names", () => {
    const client = mount();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const socket = FakeSocket.opened[0];
    expect(socket?.url).toMatch(/^ws:\/\/.*\/api\/ws$/);
    act(() => {
      socket?.open();
    });
    expect(socket?.sent).toEqual([JSON.stringify({ token: "token-1" })]);

    act(() => {
      socket?.push({ type: "ready" });
    });
    expect(liveState()).toBe("live");
    expect(liveInterval()).toBe(POLL_WHEN_LIVE_MS);

    act(() => {
      socket?.push({ type: "incident", incident_id: "INC-2026-0042", status: "ASSIGNED" });
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["incident", "INC-2026-0042"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["notifications"] });
  });

  it("shows the banner, polls quickly and reconnects with backoff when the socket drops", () => {
    mount();
    act(() => {
      FakeSocket.opened[0]?.open();
      FakeSocket.opened[0]?.push({ type: "ready" });
    });
    act(() => {
      FakeSocket.opened[0]?.drop();
    });
    expect(screen.getByTestId("live-banner")).toHaveTextContent("reconnecting");
    expect(liveInterval()).toBe(POLL_MS);

    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(FakeSocket.opened).toHaveLength(2);
    act(() => {
      FakeSocket.opened[1]?.drop();
      vi.advanceTimersByTime(1_999);
    });
    expect(FakeSocket.opened).toHaveLength(2); // the second wait is two seconds
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(FakeSocket.opened).toHaveLength(3);
  });

  it("stops for good when the server says the token is no longer valid", () => {
    mount();
    act(() => {
      FakeSocket.opened[0]?.drop(4401);
      vi.advanceTimersByTime(60_000);
    });
    expect(FakeSocket.opened).toHaveLength(1);
    expect(liveState()).toBe("off");
    expect(screen.queryByTestId("live-banner")).not.toBeInTheDocument();
  });

  it("ignores pushes it does not understand and builds the socket URL from the API's", () => {
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    applyPush(client, { type: "something-new" });
    expect(invalidate).not.toHaveBeenCalled();
    expect(liveUrl("https://api.example.edu/")).toBe("wss://api.example.edu/ws");
  });
});
