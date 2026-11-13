import type { Schemas } from "../../api/client";

type Health = Schemas["ServiceHealthResponse"];
export type ServiceState = Schemas["ServiceHealthNode"]["state"];

export const STATE_STYLE: Record<ServiceState, { label: string; box: string; dot: string }> = {
  outage: {
    label: "Outage (open P1)",
    box: "border-red-600 bg-red-50 text-red-900 dark:bg-red-950 dark:text-red-100",
    dot: "bg-red-600",
  },
  degraded: {
    label: "Degraded (open P2)",
    box: "border-amber-500 bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-100",
    dot: "bg-amber-500",
  },
  impacted: {
    label: "Impacted by a dependency",
    box: "border-dashed border-orange-500 bg-orange-50 text-orange-900 dark:bg-orange-950 dark:text-orange-100",
    dot: "bg-orange-500",
  },
  ok: {
    label: "Operational",
    box: "border-emerald-600 bg-emerald-50 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100",
    dot: "bg-emerald-600",
  },
};

const COLUMN_WIDTH = 250;
const ROW_HEIGHT = 95;
/** A depth with more services than this wraps into extra columns, so the map stays square. */
export const MAX_PER_COLUMN = 4;

/**
 * Columns by depth: a service with no dependencies sits in the first column, and every
 * service sits right of the deepest thing it depends on, so impact flows left to right. A
 * crowded depth wraps into extra columns of at most MAX_PER_COLUMN services.
 */
export function layout(health: Health): Map<number, { x: number; y: number }> {
  const dependsOn = new Map<number, number[]>();
  for (const edge of health.edges) {
    dependsOn.set(edge.service_id, [...(dependsOn.get(edge.service_id) ?? []), edge.depends_on]);
  }
  const depth = new Map<number, number>();
  const depthOf = (id: number, path: Set<number>): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (path.has(id)) return 0; // a cycle in bad data cannot loop forever
    path.add(id);
    const below = (dependsOn.get(id) ?? []).map((d) => depthOf(d, path) + 1);
    path.delete(id);
    const found = Math.max(0, ...below);
    depth.set(id, found);
    return found;
  };
  const layers = new Map<number, number[]>();
  for (const service of [...health.services].sort((a, b) => a.name.localeCompare(b.name))) {
    const d = depthOf(service.service_id, new Set());
    layers.set(d, [...(layers.get(d) ?? []), service.service_id]);
  }
  const positions = new Map<number, { x: number; y: number }>();
  let column = 0;
  for (const d of [...layers.keys()].sort((a, b) => a - b)) {
    const ids = layers.get(d) ?? [];
    ids.forEach((id, index) => {
      positions.set(id, {
        x: (column + Math.floor(index / MAX_PER_COLUMN)) * COLUMN_WIDTH,
        y: (index % MAX_PER_COLUMN) * ROW_HEIGHT,
      });
    });
    column += Math.ceil(ids.length / MAX_PER_COLUMN);
  }
  return positions;
}
