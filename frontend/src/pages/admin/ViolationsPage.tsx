import { Link } from "react-router";

import type { Schemas } from "../../api/client";
import { useRunMonitor, useViolations } from "../../api/hooks";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { DataTable } from "../../components/DataTable";
import { EmptyState, PageHeader, QueryView } from "../../components/States";
import { useToasts } from "../../components/Toasts";
import { formatDateTime } from "../../lib/format";
import { incidentPath } from "../../shell/nav";

const KIND: Record<Schemas["ViolationKind"], string> = {
  response_warning: "Response at risk",
  response_breach: "Response breached",
  resolution_warning: "Resolution at risk",
  resolution_breach: "Resolution breached",
};

/** Every warning and breach the SLA monitor has recorded (blueprint §5.2), newest first. */
export function ViolationsPage() {
  const violations = useViolations();
  const monitor = useRunMonitor();
  const toasts = useToasts();
  return (
    <>
      <PageHeader
        title="SLA violations"
        subtitle="Warnings at 75% of a target and breaches past it, recorded once each by the monitor."
        actions={
          <Button
            busy={monitor.isPending}
            onClick={() => {
              monitor.mutate(undefined, {
                onSuccess: (report) => {
                  toasts.info(
                    `Monitor ran: ${String(report.warned)} warned, ${String(report.breached)} breached, ${String(report.escalated.length)} escalated, ${String(report.auto_closed.length)} auto-closed.`,
                  );
                },
                onError: (error) => {
                  toasts.error(error);
                },
              });
            }}
          >
            Run the monitor now
          </Button>
        }
      />
      <QueryView
        query={violations}
        loadingLabel="Loading violations"
        isEmpty={(rows) => rows.length === 0}
        empty={<EmptyState title="No SLA warnings or breaches recorded" />}
      >
        {(rows) => (
          <DataTable
            caption="SLA violations"
            rows={rows}
            rowKey={(row) => `${row.incident_id}-${row.kind}-${String(row.cycle)}`}
            columns={[
              {
                key: "incident",
                header: "Incident",
                cell: (row) => (
                  <Link
                    className="font-mono text-xs underline"
                    to={incidentPath("admin", row.incident_id)}
                  >
                    {row.incident_id}
                  </Link>
                ),
              },
              {
                key: "kind",
                header: "What happened",
                cell: (row) => (
                  <Badge tone={row.is_breach ? "bad" : "warn"}>{KIND[row.kind]}</Badge>
                ),
              },
              { key: "deadline", header: "Deadline", cell: (row) => formatDateTime(row.deadline) },
              {
                key: "detected",
                header: "Detected",
                cell: (row) => formatDateTime(row.detected_at),
              },
              {
                key: "escalated",
                header: "Escalated to",
                cell: (row) =>
                  row.escalated_to_level === null ? "—" : `Level ${String(row.escalated_to_level)}`,
              },
            ]}
          />
        )}
      </QueryView>
    </>
  );
}
