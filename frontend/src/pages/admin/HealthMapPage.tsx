import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useMemo } from "react";

import type { Schemas } from "../../api/client";
import { useServiceHealth } from "../../api/hooks";
import { DataTable, type Column } from "../../components/DataTable";
import { Card, PageHeader, QueryView } from "../../components/States";
import { STATE_STYLE, layout } from "./healthLayout";

type Health = Schemas["ServiceHealthResponse"];
type ServiceNode = Schemas["ServiceHealthNode"];
type State = ServiceNode["state"];

/**
 * P4.11: the live service health map. Each campus service is coloured by its open incidents
 * and by what it depends on, so an outage in a shared service (the Database Cluster) shows up
 * at once in everything built on it (the Fee Payment Portal). Live pushes refresh it.
 */

type ServiceFlowNode = Node<{ service: ServiceNode }, "service">;

function ServiceBox({ data }: NodeProps<ServiceFlowNode>) {
  const { service } = data;
  const style = STATE_STYLE[service.state];
  return (
    <div
      className={`w-52 rounded-lg border-2 px-3 py-2 text-xs shadow-sm ${style.box}`}
      data-testid={`health-node-${String(service.service_id)}`}
      data-state={service.state}
    >
      <Handle type="target" position={Position.Left} className="!opacity-0" />
      <div className="flex items-center gap-2 font-semibold">
        <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${style.dot}`} />
        {service.name}
      </div>
      <div className="mt-1 opacity-80">
        {service.open_incidents === 0
          ? "No open incidents"
          : `${String(service.open_incidents)} open · ${String(service.open_p1)} P1 · ${String(service.open_p2)} P2`}
      </div>
      <Handle type="source" position={Position.Right} className="!opacity-0" />
    </div>
  );
}

const NODE_TYPES = { service: ServiceBox };

function HealthMap({ health }: { health: Health }) {
  const { nodes, edges } = useMemo(() => {
    const positions = layout(health);
    const byId = new Map(health.services.map((s) => [s.service_id, s]));
    const nodes: ServiceFlowNode[] = health.services.map((service) => ({
      id: String(service.service_id),
      type: "service",
      position: positions.get(service.service_id) ?? { x: 0, y: 0 },
      data: { service },
      draggable: false,
      connectable: false,
    }));
    const edges: Edge[] = health.edges.map((edge) => {
      const source = byId.get(edge.depends_on);
      const failing = source !== undefined && source.state !== "ok";
      return {
        // Drawn from the dependency to what is built on it: the way an outage spreads.
        id: `${String(edge.depends_on)}-${String(edge.service_id)}`,
        source: String(edge.depends_on),
        target: String(edge.service_id),
        animated: failing,
        markerEnd: { type: MarkerType.ArrowClosed },
        style: failing ? { stroke: "#dc2626", strokeWidth: 2 } : { stroke: "#94a3b8" },
      };
    });
    return { nodes, edges };
  }, [health]);

  return (
    <div className="h-[32rem] w-full overflow-hidden rounded-lg border border-line bg-surface">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        minZoom={0.3}
        ariaLabelConfig={{ "controls.ariaLabel": "Map zoom controls" }}
      >
        <Background gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

const COLUMNS: Column<ServiceNode & { causes: string }>[] = [
  {
    key: "name",
    header: "Service",
    cell: (row) => <span className="font-medium">{row.name}</span>,
  },
  {
    key: "state",
    header: "State",
    cell: (row) => (
      <span className="inline-flex items-center gap-2">
        <span
          aria-hidden="true"
          className={`h-2.5 w-2.5 rounded-full ${STATE_STYLE[row.state].dot}`}
        />
        {STATE_STYLE[row.state].label}
      </span>
    ),
  },
  { key: "open", header: "Open", align: "right", cell: (row) => String(row.open_incidents) },
  { key: "p1", header: "P1", align: "right", cell: (row) => String(row.open_p1) },
  { key: "p2", header: "P2", align: "right", cell: (row) => String(row.open_p2) },
  { key: "cause", header: "Trouble comes from", cell: (row) => row.causes || "—" },
];

const ORDER: Record<State, number> = { outage: 0, degraded: 1, impacted: 2, ok: 3 };

export function HealthMapPage() {
  const health = useServiceHealth();
  return (
    <>
      <PageHeader
        title="Service health"
        subtitle="Every campus service, coloured by its open incidents and by the services it depends on. Updates live."
      />
      <QueryView
        query={health}
        loadingLabel="Loading the service map"
        isEmpty={(data) => data.services.length === 0}
        empty={<p className="text-sm text-muted">No active services are configured.</p>}
      >
        {(data) => {
          const names = new Map(data.services.map((s) => [s.service_id, s.name]));
          const rows = [...data.services]
            .sort((a, b) => ORDER[a.state] - ORDER[b.state] || a.name.localeCompare(b.name))
            .map((s) => ({
              ...s,
              causes: s.caused_by.map((id) => names.get(id) ?? `Service ${String(id)}`).join(", "),
            }));
          const counts = data.services.reduce<Record<State, number>>(
            (acc, s) => ({ ...acc, [s.state]: acc[s.state] + 1 }),
            { outage: 0, degraded: 0, impacted: 0, ok: 0 },
          );
          return (
            <div className="space-y-5">
              <ul aria-label="Legend" className="flex flex-wrap gap-4 text-sm">
                {(Object.keys(STATE_STYLE) as State[]).map((state) => (
                  <li key={state} className="inline-flex items-center gap-2">
                    <span
                      aria-hidden="true"
                      className={`h-3 w-3 rounded-full ${STATE_STYLE[state].dot}`}
                    />
                    {STATE_STYLE[state].label}: <strong>{counts[state]}</strong>
                  </li>
                ))}
              </ul>
              <HealthMap health={data} />
              <p className="text-xs text-muted">
                Arrows run from a service to the services built on it, the way an outage spreads;
                red, moving arrows carry trouble.
              </p>
              <Card>
                <DataTable
                  caption="Service health, worst first"
                  columns={COLUMNS}
                  rows={rows}
                  rowKey={(row) => row.service_id}
                />
              </Card>
            </div>
          );
        }}
      </QueryView>
    </>
  );
}
