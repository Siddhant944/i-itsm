import { Link } from "react-router";

import { useMyIncidents } from "../../api/hooks";
import { IncidentTable } from "../../components/IncidentTable";
import { EmptyState, PageHeader, QueryView } from "../../components/States";
import { usePortal } from "../../lib/usePortal";
import { incidentPath } from "../../shell/nav";

const LINK_BUTTON =
  "inline-flex items-center rounded-md bg-accent px-3.5 py-2 text-sm font-medium text-accent-ink hover:bg-accent-strong";

/** Everything the signed-in person has reported, newest first (BR-01: only their own). */
export function MyIncidentsPage() {
  const portal = usePortal();
  const incidents = useMyIncidents();
  const reportPath = `/${portal}/report`;
  return (
    <>
      <PageHeader
        title="My incidents"
        subtitle="Everything you have reported, and where each one stands."
        actions={
          <Link to={reportPath} className={LINK_BUTTON}>
            Report an incident
          </Link>
        }
      />
      <QueryView
        query={incidents}
        loadingLabel="Loading your incidents"
        isEmpty={(rows) => rows.length === 0}
        empty={
          <EmptyState
            title="You have not reported anything yet"
            hint="When something is not working, tell us and we will track it here."
            action={
              <Link to={reportPath} className={LINK_BUTTON}>
                Report an incident
              </Link>
            }
          />
        }
      >
        {(rows) => (
          <IncidentTable
            caption="My incidents"
            incidents={rows}
            hrefFor={(id) => incidentPath(portal, id)}
            show={["assignee"]}
          />
        )}
      </QueryView>
    </>
  );
}
