import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Schemas } from "../../api/client";
import { downloadCsv, useDashboard } from "../../api/hooks";
import { Button } from "../../components/Button";
import { DataTable } from "../../components/DataTable";
import { Card, PageHeader, QueryView } from "../../components/States";
import { useToasts } from "../../components/Toasts";
import { formatDay, formatHours, formatPercent } from "../../lib/format";
import { WORKLOAD_COLUMNS } from "../technician/WorkloadPage";

const WINDOWS = [7, 30, 90] as const;

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <p className="text-xs tracking-wide text-muted uppercase">{label}</p>
      <p className="mt-1 text-2xl font-semibold" data-testid={`stat-${label}`}>
        {value}
      </p>
      {hint !== undefined && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
    </div>
  );
}

function Charts({ data }: { data: Schemas["DashboardResponse"] }) {
  const trend = data.trend.map((point) => ({ ...point, day: formatDay(point.day) }));
  const services = [...data.services].sort((a, b) => b.incidents - a.incidents).slice(0, 8);
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Card title="Reported and resolved per day">
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={trend}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
              <XAxis dataKey="day" fontSize={11} />
              <YAxis allowDecimals={false} fontSize={11} />
              <Tooltip />
              <Legend />
              <Line
                type="monotone"
                dataKey="reported"
                name="Reported"
                stroke="#4338ca"
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="resolved"
                name="Resolved"
                stroke="#059669"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>
      <Card title="Incidents and breaches by service">
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={services} layout="vertical" margin={{ left: 40 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
              <XAxis type="number" allowDecimals={false} fontSize={11} />
              <YAxis type="category" dataKey="name" width={130} fontSize={11} />
              <Tooltip />
              <Legend />
              <Bar dataKey="incidents" name="Incidents" fill="#4338ca" />
              <Bar dataKey="breached" name="Breached" fill="#dc2626" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  );
}

/** Overview cards, the nine figures of §9, workload and service analysis. */
export function DashboardPage() {
  const [windowDays, setWindowDays] = useState<number>(30);
  const dashboard = useDashboard(windowDays);
  const toasts = useToasts();
  const exportCsv = (
    path: "/reports/workload/export" | "/reports/services/export",
    name: string,
  ) => {
    downloadCsv(path, name).catch((error: unknown) => {
      toasts.error(error);
    });
  };

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Live figures for the help desk. Averages cover the chosen window."
        actions={
          <div role="group" aria-label="Window" className="flex gap-1">
            {WINDOWS.map((days) => (
              <Button
                key={days}
                small
                variant={days === windowDays ? "primary" : "secondary"}
                aria-pressed={days === windowDays}
                onClick={() => {
                  setWindowDays(days);
                }}
              >
                {String(days)} days
              </Button>
            ))}
          </div>
        }
      />
      <QueryView query={dashboard} loadingLabel="Loading the dashboard">
        {(data) => (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <Stat label="Open" value={String(data.overview.open_count)} />
              <Stat label="Critical open" value={String(data.overview.critical_open)} hint="P1" />
              <Stat label="At risk" value={String(data.overview.at_risk)} />
              <Stat
                label="Breached"
                value={String(data.overview.breached)}
                hint={`${formatPercent(data.overview.breached_share)} of all incidents`}
              />
              <Stat label="Unassigned" value={String(data.overview.unassigned)} />
              <Stat label="Awaiting reporter" value={String(data.overview.awaiting_reporter)} />
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <Stat
                label="MTTA"
                value={formatHours(data.metrics.mtta_hours)}
                hint="to acknowledge"
              />
              <Stat label="MTTR" value={formatHours(data.metrics.mttr_hours)} hint="to resolve" />
              <Stat
                label="SLA compliance"
                value={
                  data.metrics.sla_measured === 0 ? "—" : formatPercent(data.metrics.sla_compliance)
                }
                hint={`${String(data.metrics.sla_measured)} measured`}
              />
              <Stat
                label="CSAT"
                value={data.metrics.csat === null ? "—" : `${data.metrics.csat.toFixed(1)} / 5`}
                hint={`${String(data.metrics.csat_responses)} ratings`}
              />
              <Stat
                label="Reopen rate"
                value={data.metrics.resolved === 0 ? "—" : formatPercent(data.metrics.reopen_rate)}
                hint={`${String(data.metrics.reopened)} reopened`}
              />
              <Stat
                label="Resolved"
                value={String(data.overview.resolved_in_window)}
                hint="in window"
              />
            </div>
            <Charts data={data} />
            <Card
              title="Technician workload"
              actions={
                <Button
                  small
                  onClick={() => {
                    exportCsv("/reports/workload/export", "workload.csv");
                  }}
                >
                  Export CSV
                </Button>
              }
            >
              <DataTable
                caption="Technician workload"
                columns={WORKLOAD_COLUMNS}
                rows={data.workload}
                rowKey={(row) => row.technician_id}
              />
            </Card>
            <Card
              title="Service analysis"
              actions={
                <Button
                  small
                  onClick={() => {
                    exportCsv("/reports/services/export", "services.csv");
                  }}
                >
                  Export CSV
                </Button>
              }
            >
              <DataTable
                caption="Service analysis"
                rows={data.services}
                rowKey={(row) => row.service_id}
                columns={[
                  { key: "name", header: "Service", cell: (row) => row.name },
                  {
                    key: "n",
                    header: "Incidents",
                    align: "right",
                    cell: (row) => String(row.incidents),
                  },
                  {
                    key: "b",
                    header: "Breached",
                    align: "right",
                    cell: (row) => String(row.breached),
                  },
                  {
                    key: "s",
                    header: "Breach share",
                    align: "right",
                    cell: (row) => (row.incidents === 0 ? "—" : formatPercent(row.breach_share)),
                  },
                  {
                    key: "m",
                    header: "MTTR",
                    align: "right",
                    cell: (row) => formatHours(row.mttr_hours),
                  },
                ]}
              />
            </Card>
          </div>
        )}
      </QueryView>
    </>
  );
}
