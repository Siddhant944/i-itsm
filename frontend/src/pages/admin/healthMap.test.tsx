import { screen, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import type { Schemas } from "../../api/client";
import { me, renderPage } from "../../test/utils";
import { HealthMapPage } from "./HealthMapPage";
import { layout } from "./healthLayout";

type Node = Schemas["ServiceHealthNode"];

function node(id: number, name: string, state: Node["state"], extra: Partial<Node> = {}): Node {
  return {
    service_id: id,
    name,
    criticality: 3,
    sla_tier: "gold",
    state,
    open_incidents: 0,
    open_p1: 0,
    open_p2: 0,
    caused_by: [],
    ...extra,
  };
}

// The campus in miniature: the portal sits on the database, which sits on the network.
const HEALTH: Schemas["ServiceHealthResponse"] = {
  services: [
    node(1, "Campus Network Core", "ok"),
    node(2, "Database Cluster", "outage", { open_incidents: 2, open_p1: 1 }),
    node(3, "Fee Payment Portal", "impacted", { caused_by: [2] }),
  ],
  edges: [
    { service_id: 2, depends_on: 1 },
    { service_id: 3, depends_on: 2 },
  ],
};

beforeAll(() => {
  // React Flow measures its canvas; jsdom has no layout engine.
  if (!("ResizeObserver" in globalThis)) {
    Object.assign(globalThis, {
      ResizeObserver: class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    });
  }
});

describe("service health map (P4.11)", () => {
  it("puts each service one column right of what it depends on", () => {
    const positions = layout(HEALTH);
    expect(positions.get(1)?.x).toBe(0);
    expect(positions.get(2)?.x).toBeGreaterThan(positions.get(1)?.x ?? 0);
    expect(positions.get(3)?.x).toBeGreaterThan(positions.get(2)?.x ?? 0);
  });

  it("wraps a crowded layer into extra columns", () => {
    const many = Array.from({ length: 9 }, (_, i) => node(10 + i, `Service ${String(i)}`, "ok"));
    const wide = {
      services: [node(1, "Core", "ok"), ...many],
      edges: many.map((n) => ({ service_id: n.service_id, depends_on: 1 })),
    };
    const positions = layout(wide);
    const columns = new Set(many.map((n) => positions.get(n.service_id)?.x));
    expect(columns.size).toBe(3); // 9 services, at most 4 to a column
    expect(Math.min(...[...columns].map(Number))).toBeGreaterThan(positions.get(1)?.x ?? 0);
  });

  it("survives a dependency cycle in bad data", () => {
    const looped = { ...HEALTH, edges: [...HEALTH.edges, { service_id: 1, depends_on: 3 }] };
    expect(layout(looped).size).toBe(3);
  });

  it("names the outage and where the impact comes from, worst first", async () => {
    renderPage(<HealthMapPage />, {
      user: me("administrator"),
      routes: { "GET /reports/service-health": HEALTH },
    });
    const table = await screen.findByRole("table", { name: /Service health, worst first/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Database Cluster");
    expect(rows[0]).toHaveTextContent("Outage (open P1)");
    expect(rows[1]).toHaveTextContent("Fee Payment Portal");
    expect(rows[1]).toHaveTextContent("Database Cluster"); // where its trouble comes from
    expect(screen.getByRole("list", { name: "Legend" })).toHaveTextContent("Outage (open P1): 1");
  });
});
