import { useNavigate } from "react-router";

import type { IncidentSummary } from "../api/hooks";
import { useNames } from "../api/hooks";
import { formatDateTime } from "../lib/format";
import { slaDueAt } from "../lib/sla";
import { PriorityBadge, StatusBadge } from "./Badge";
import { DataTable, type Column } from "./DataTable";
import { SLAChip } from "./SLAChip";

type Optional = "reporter" | "assignee" | "category";

const PRIORITY_RANK: Record<string, number> = { P1: 1, P2: 2, P3: 3, P4: 4 };
/** The lifecycle's own order (§4), so a sort by status reads like the incident's progress. */
const STATUS_ORDER: readonly IncidentSummary["status"][] = [
  "NEW",
  "CLASSIFIED",
  "ASSIGNED",
  "ACKNOWLEDGED",
  "IN_PROGRESS",
  "ON_HOLD",
  "RESOLVED",
  "VERIFIED",
  "CLOSED",
  "CANCELLED",
];

interface IncidentTableProps {
  caption: string;
  incidents: readonly IncidentSummary[];
  /** Where a row opens; each portal keeps the reader inside itself. */
  hrefFor: (id: string) => string;
  show?: readonly Optional[] | undefined;
  /** Off where the server sorts and pages the rows, so a header click cannot sort one page only. */
  sortable?: boolean | undefined;
}

/** The incident list every portal uses: same badges, same SLA chip, different columns. */
export function IncidentTable({
  caption,
  incidents,
  hrefFor,
  show = [],
  sortable = true,
}: IncidentTableProps) {
  const navigate = useNavigate();
  const names = useNames();
  const columns: Column<IncidentSummary>[] = [
    {
      key: "id",
      header: "Incident",
      sortValue: (row) => row.id,
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
      sortValue: (row) => PRIORITY_RANK[row.priority ?? ""] ?? null,
      cell: (row) => <PriorityBadge priority={row.priority} />,
    },
    {
      key: "status",
      header: "Status",
      sortValue: (row) => STATUS_ORDER.indexOf(row.status),
      cell: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "sla",
      header: "SLA",
      sortValue: (row) => slaDueAt(row.sla, row.status),
      cell: (row) => <SLAChip sla={row.sla} status={row.status} />,
    },
    {
      key: "service",
      header: "Service",
      sortValue: (row) => names.service(row.service_id),
      cell: (row) => names.service(row.service_id),
    },
  ];
  if (show.includes("category")) {
    columns.push({
      key: "category",
      header: "Category",
      sortValue: (row) => (row.category_id === null ? null : names.category(row.category_id)),
      cell: (row) => names.category(row.category_id),
    });
  }
  if (show.includes("reporter")) {
    columns.push({
      key: "reporter",
      header: "Reported by",
      sortValue: (row) => names.person(row.reporter_id),
      cell: (row) => names.person(row.reporter_id),
    });
  }
  if (show.includes("assignee")) {
    columns.push({
      key: "assignee",
      header: "Assigned to",
      sortValue: (row) => (row.assignee_id === null ? null : names.person(row.assignee_id)),
      cell: (row) => names.person(row.assignee_id),
    });
  }
  columns.push({
    key: "created",
    header: "Reported",
    sortValue: (row) => Date.parse(row.created_at),
    cell: (row) => <span className="whitespace-nowrap">{formatDateTime(row.created_at)}</span>,
  });

  return (
    <DataTable
      caption={caption}
      columns={sortable ? columns : columns.map((column) => ({ ...column, sortValue: undefined }))}
      rows={incidents}
      rowKey={(row) => row.id}
      onRowClick={(row) => {
        void navigate(hrefFor(row.id));
      }}
    />
  );
}
