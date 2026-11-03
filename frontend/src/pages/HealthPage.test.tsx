import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HealthPage } from "./HealthPage";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <HealthPage />
    </QueryClientProvider>,
  );
}

function mockFetch(response: Response | Promise<Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => response),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HealthPage", () => {
  it("shows a loading state while the request is pending", () => {
    mockFetch(new Promise<Response>(() => undefined));
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("Checking the API");
  });

  it("shows the API and database status on success", async () => {
    const body = { status: "ok", app: "I-ITSM", version: "0.1.0", env: "test", database: "ok" };
    mockFetch(Response.json(body));
    renderPage();
    expect(await screen.findByTestId("api-status")).toHaveTextContent("ok");
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
  });

  it("shows an error with a retry button when the API fails", async () => {
    mockFetch(new Response("down", { status: 503 }));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Health check failed (503)");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
