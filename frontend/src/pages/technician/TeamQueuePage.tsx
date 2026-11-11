import { useSearch, type SearchFilters } from "../../api/hooks";
import { IncidentTable } from "../../components/IncidentTable";
import { EmptyState, PageHeader, QueryView } from "../../components/States";
import { byUrgency } from "../../lib/sort";
import { usePortal } from "../../lib/usePortal";
import { incidentPath } from "../../shell/nav";

/** Open work only; the API narrows the result to the lead's own team (BR-01). */
const OPEN_TEAM_WORK: SearchFilters = {
  statuses: ["NEW", "CLASSIFIED", "ASSIGNED", "ACKNOWLEDGED", "IN_PROGRESS", "ON_HOLD", "RESOLVED"],
  limit: 100,
  offset: 0,
  sort_by: "created_at",
  descending: false,
};

/** The Team Lead's view: everything open in the team, including what is waiting for a person. */
export function TeamQueuePage() {
  const portal = usePortal();
  const team = useSearch(OPEN_TEAM_WORK, true);
  return (
    <>
      <PageHeader
        title="Team queue"
        subtitle="Open incidents across your team. Open one to reassign it or see who is suggested."
      />
      <QueryView
        query={team}
        loadingLabel="Loading the team queue"
        isEmpty={(page) => page.items.length === 0}
        empty={<EmptyState title="Nothing open in your team" />}
      >
        {(page) => (
          <>
            <IncidentTable
              caption="Team queue"
              incidents={[...page.items].sort(byUrgency)}
              hrefFor={(id) => incidentPath(portal, id)}
              show={["assignee", "reporter"]}
            />
            {page.has_more && (
              <p className="mt-2 text-xs text-muted">
                Showing the first {String(page.items.length)} of {String(page.total)}.
              </p>
            )}
          </>
        )}
      </QueryView>
    </>
  );
}
