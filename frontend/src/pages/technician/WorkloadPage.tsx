import type { Schemas } from "../../api/client";
import { useWorkload } from "../../api/hooks";
import { Badge } from "../../components/Badge";
import { DataTable, type Column } from "../../components/DataTable";
import { LoadBar } from "../../components/LoadBar";
import { EmptyState, PageHeader, QueryView } from "../../components/States";

type Row = Schemas["WorkloadRowResponse"];

// eslint-disable-next-line react-refresh/only-export-components -- shared with the admin dashboard
export const WORKLOAD_COLUMNS: Column<Row>[] = [
  {
    key: "name",
    header: "Technician",
    cell: (row) => <span className="font-medium">{row.name}</span>,
  },
  {
    key: "load",
    header: "Weighted load",
    cell: (row) => <LoadBar load={row.weighted_load} max={row.max_load} />,
  },
  { key: "open", header: "Open", align: "right", cell: (row) => String(row.open_count) },
  { key: "resolved", header: "Resolved", align: "right", cell: (row) => String(row.resolved) },
  {
    key: "state",
    header: "Status",
    cell: (row) =>
      !row.available ? (
        <Badge>Unavailable</Badge>
      ) : row.at_capacity ? (
        <Badge tone="bad">At capacity</Badge>
      ) : (
        <Badge tone="good">Available</Badge>
      ),
  },
];

/** The caller's own load, or the whole team's for a Team Lead (the API decides which). */
export function WorkloadPage() {
  const workload = useWorkload();
  return (
    <>
      <PageHeader
        title="Workload"
        subtitle="Open incidents weigh 4, 3, 2 and 1 points for P1 to P4. Nobody is assigned past 10."
      />
      <QueryView
        query={workload}
        loadingLabel="Loading workload"
        isEmpty={(rows) => rows.length === 0}
        empty={<EmptyState title="No workload to show" />}
      >
        {(rows) => (
          <DataTable
            caption="Workload"
            columns={WORKLOAD_COLUMNS}
            rows={rows}
            rowKey={(row) => row.technician_id}
          />
        )}
      </QueryView>
    </>
  );
}
