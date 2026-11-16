import { useId, useState } from "react";

import { useQueue } from "../../api/hooks";
import { IncidentTable } from "../../components/IncidentTable";
import { EmptyState, PageHeader, QueryView } from "../../components/States";
import { byUrgency, isFinished } from "../../lib/sort";
import { usePortal } from "../../lib/usePortal";
import { incidentPath } from "../../shell/nav";

/**
 * What the signed-in technician is carrying. Finished incidents stay hidden until asked for, so
 * the queue opens on work still to do, as the large service desks' queues do.
 */
export function QueuePage() {
  const portal = usePortal();
  const queue = useQueue();
  const [withFinished, setWithFinished] = useState(false);
  const toggleId = useId();
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
        {(rows) => {
          const finished = rows.filter(isFinished).length;
          const shown = withFinished ? rows : rows.filter((row) => !isFinished(row));
          return (
            <>
              {finished > 0 && (
                <div className="mb-3 flex items-center gap-2 text-sm text-muted">
                  <input
                    id={toggleId}
                    type="checkbox"
                    checked={withFinished}
                    onChange={(event) => {
                      setWithFinished(event.target.checked);
                    }}
                    className="size-4 accent-accent"
                  />
                  <label htmlFor={toggleId}>
                    Show finished incidents ({String(finished)} verified, closed or cancelled)
                  </label>
                </div>
              )}
              {shown.length === 0 ? (
                <EmptyState
                  title="Nothing open right now"
                  hint="Everything assigned to you is finished. Tick the box above to see it."
                />
              ) : (
                <IncidentTable
                  caption="My queue"
                  incidents={[...shown].sort(byUrgency)}
                  hrefFor={(id) => incidentPath(portal, id)}
                  show={["category", "reporter"]}
                />
              )}
            </>
          );
        }}
      </QueryView>
    </>
  );
}
