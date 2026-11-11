import { useState } from "react";
import { Link } from "react-router";

import { useAudit, useNames, useVerifyAudit } from "../../api/hooks";
import { Button } from "../../components/Button";
import { DataTable } from "../../components/DataTable";
import { TextField } from "../../components/Field";
import { EmptyState, ErrorState, PageHeader, QueryView } from "../../components/States";
import { formatDateTime, titleCase } from "../../lib/format";
import { incidentPath } from "../../shell/nav";

const PAGE_SIZE = 50;

function detailText(details: Record<string, unknown>): string {
  return Object.entries(details)
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(" · ");
}

/** The hash-chained audit log and its integrity check (blueprint §8, BR-10). */
export function AuditPage() {
  const [offset, setOffset] = useState(0);
  const [typed, setTyped] = useState("");
  const [incidentId, setIncidentId] = useState("");
  const audit = useAudit(offset, PAGE_SIZE, incidentId);
  const verify = useVerifyAudit();
  const names = useNames();

  return (
    <>
      <PageHeader
        title="Audit log"
        subtitle="Every state change, sign-in, override and configuration change, newest first."
        actions={
          <Button
            variant="primary"
            busy={verify.isPending}
            onClick={() => {
              verify.mutate();
            }}
          >
            Verify integrity
          </Button>
        }
      />

      {verify.isError && <ErrorState error={verify.error} />}
      {verify.data !== undefined && (
        <div
          role="status"
          data-testid="integrity-result"
          className={`mb-4 rounded-lg border px-4 py-3 text-sm font-medium ${verify.data.intact ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-800" : "border-red-500/50 bg-red-500/10 text-red-700"}`}
        >
          {verify.data.intact ? "✓ " : "✗ "}
          {verify.data.summary}
        </div>
      )}

      <form
        className="mb-4 flex items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setIncidentId(typed.trim());
          setOffset(0);
        }}
      >
        <div className="w-64">
          <TextField
            label="Incident ID"
            placeholder="INC-2026-0001"
            value={typed}
            onChange={(event) => {
              setTyped(event.target.value);
            }}
          />
        </div>
        <Button type="submit">Filter</Button>
        {incidentId !== "" && (
          <Button
            variant="ghost"
            onClick={() => {
              setTyped("");
              setIncidentId("");
              setOffset(0);
            }}
          >
            Clear
          </Button>
        )}
      </form>

      <QueryView
        query={audit}
        loadingLabel="Loading the audit log"
        isEmpty={(page) => page.total === 0}
        empty={<EmptyState title="No audit records" />}
      >
        {(page) => (
          <>
            <p className="mb-2 text-sm text-muted">{String(page.total)} records</p>
            <DataTable
              caption="Audit log"
              rows={page.items}
              rowKey={(row) => row.sequence}
              columns={[
                {
                  key: "seq",
                  header: "#",
                  cell: (row) => <span className="font-mono text-xs">{String(row.sequence)}</span>,
                },
                {
                  key: "when",
                  header: "When",
                  cell: (row) => (
                    <span className="whitespace-nowrap">{formatDateTime(row.occurred_at)}</span>
                  ),
                },
                { key: "action", header: "Action", cell: (row) => titleCase(row.action) },
                {
                  key: "actor",
                  header: "Actor",
                  cell: (row) => (row.actor_id === null ? "System" : names.person(row.actor_id)),
                },
                {
                  key: "incident",
                  header: "Incident",
                  cell: (row) =>
                    row.incident_id === null ? (
                      "—"
                    ) : (
                      <Link
                        className="font-mono text-xs underline"
                        to={incidentPath("admin", row.incident_id)}
                      >
                        {row.incident_id}
                      </Link>
                    ),
                },
                {
                  key: "details",
                  header: "Details",
                  cell: (row) => (
                    <span className="text-xs text-muted">{detailText(row.details)}</span>
                  ),
                },
                {
                  key: "hash",
                  header: "Hash",
                  cell: (row) => (
                    <span className="font-mono text-xs text-muted" title={row.hash}>
                      {row.hash.slice(0, 10)}…
                    </span>
                  ),
                },
              ]}
            />
            <div className="mt-3 flex gap-2">
              <Button
                disabled={offset === 0}
                onClick={() => {
                  setOffset(Math.max(0, offset - PAGE_SIZE));
                }}
              >
                Newer
              </Button>
              <Button
                disabled={offset + PAGE_SIZE >= page.total}
                onClick={() => {
                  setOffset(offset + PAGE_SIZE);
                }}
              >
                Older
              </Button>
            </div>
          </>
        )}
      </QueryView>
    </>
  );
}
