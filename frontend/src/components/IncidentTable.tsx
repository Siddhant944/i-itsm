import { useNavigate } from "react-router";

import type { IncidentSummary } from "../api/hooks";
import { useNames } from "../api/hooks";
import { formatDateTime } from "../lib/format";
import { PriorityBadge, StatusBadge } from "./Badge";
import { DataTable, type Column } from "./DataTable";
import { SLAChip } from "./SLAChip";

type Optional = "reporter" | "assignee" | "category";

interface IncidentTableProps {
  caption: string;
  incidents: readonly IncidentSummary[];
  /** Where a row opens; each portal keeps the reader inside itself. */
  hrefFor: (id: string) => string;
  show?: readonly Optional[] | undefined;
}

/** The incident list every portal uses: same badges, same SLA chip, different columns. */
export function IncidentTable({ caption, incidents, hrefFor, show = [] }: IncidentTableProps) {
  const navigate = useNavigate();
  const names = useNames();
  const columns: Column<IncidentSummary>[] = [
    {
      key: "id",
      header: "Incident",
      cell: (row) => (
        <div>
          <p className="font-mono text-xs text-muted">{row.id}</p>
          <p className="font-medium">{row.title}</p>
        </div>
      ),
    },
    {
      key: "priority",
      header: "Priority",
      cell: (row) => <PriorityBadge priority={row.priority} />,
    },
    { key: "status", header: "Status", cell: (row) => <StatusBadge status={row.status} /> },
    { key: "sla", header: "SLA", cell: (row) => <SLAChip sla={row.sla} status={row.status} /> },
    { key: "service", header: "Service", cell: (row) => names.service(row.service_id) },
  ];
  if (show.includes("category")) {
    columns.push({
      key: "category",
      header: "Category",
      cell: (row) => names.category(row.category_id),
    });
  }
  if (show.includes("reporter")) {
    columns.push({
      key: "reporter",
      header: "Reported by",
      cell: (row) => names.person(row.reporter_id),
    });
  }
  if (show.includes("assignee")) {
    columns.push({
      key: "assignee",
      header: "Assigned to",
      cell: (row) => names.person(row.assignee_id),
    });
  }
  columns.push({
    key: "created",
    header: "Reported",
    cell: (row) => <span className="whitespace-nowrap">{formatDateTime(row.created_at)}</span>,
  });

  return (
    <DataTable
      caption={caption}
      columns={columns}
      rows={incidents}
      rowKey={(row) => row.id}
      onRowClick={(row) => {
        void navigate(hrefFor(row.id));
      }}
    />
  );
}
