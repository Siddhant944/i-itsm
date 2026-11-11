import { useQueue } from "../../api/hooks";
import { IncidentTable } from "../../components/IncidentTable";
import { EmptyState, PageHeader, QueryView } from "../../components/States";
import { byUrgency } from "../../lib/sort";
import { usePortal } from "../../lib/usePortal";
import { incidentPath } from "../../shell/nav";

/** What the signed-in technician is carrying. */
export function QueuePage() {
  const portal = usePortal();
  const queue = useQueue();
  return (
    <>
      <PageHeader title="My queue" subtitle="Incidents assigned to you, most urgent first." />
      <QueryView
        query={queue}
        loadingLabel="Loading your queue"
        isEmpty={(rows) => rows.length === 0}
        empty={
          <EmptyState
            title="Your queue is empty"
            hint="New incidents appear here as soon as they are assigned to you."
          />
        }
      >
        {(rows) => (
          <IncidentTable
            caption="My queue"
            incidents={[...rows].sort(byUrgency)}
            hrefFor={(id) => incidentPath(portal, id)}
            show={["category", "reporter"]}
          />
        )}
      </QueryView>
    </>
  );
}
