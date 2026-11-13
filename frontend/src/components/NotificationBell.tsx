import { useState } from "react";
import { Link } from "react-router";

import { useMarkRead, useNotifications } from "../api/hooks";
import { formatDateTime } from "../lib/format";
import { ErrorState, Skeleton } from "./States";

/** The in-app channel (blueprint §5.4): unread count, the latest items, mark as read. */
export function NotificationBell({ incidentHref }: { incidentHref: (id: string) => string }) {
  const [open, setOpen] = useState(false);
  const bell = useNotifications();
  const markRead = useMarkRead();
  const unread = bell.data?.unread ?? 0;

  return (
    <div className="relative">
      <button
        type="button"
        aria-label={`Notifications, ${String(unread)} unread`}
        aria-expanded={open}
        onClick={() => {
          setOpen((value) => !value);
        }}
        className="relative rounded-md px-2 py-1 text-lg leading-none hover:bg-current/10 focus-visible:outline-2 focus-visible:outline-accent"
      >
        <span aria-hidden="true">🔔</span>
        {unread > 0 && (
          <span
            data-testid="unread-count"
            className="absolute -top-1 -right-1 min-w-5 rounded-full bg-danger px-1 text-center text-xs font-semibold text-white"
          >
            {unread > 99 ? "99+" : String(unread)}
          </span>
        )}
      </button>
      {open && (
        <div
          role="region"
          aria-label="Notifications"
          className="absolute right-0 z-30 mt-2 max-h-[70vh] w-80 overflow-y-auto rounded-lg border border-line bg-surface p-2 text-ink shadow-xl"
        >
          {bell.isPending && <Skeleton rows={3} label="Loading notifications" />}
          {bell.isError && (
            <ErrorState
              error={bell.error}
              onRetry={() => {
                void bell.refetch();
              }}
            />
          )}
          {bell.data?.latest.length === 0 && (
            <p className="px-2 py-6 text-center text-sm text-muted">No notifications yet.</p>
          )}
          <ul className="space-y-1">
            {bell.data?.latest.map((item) => (
              <li
                key={item.id}
                className={`rounded-md px-2 py-2 text-sm ${item.read_at === null ? "bg-accent-soft" : ""}`}
              >
                <p className="font-medium">{item.subject}</p>
                <p className="text-xs text-muted">{formatDateTime(item.created_at)}</p>
                <div className="mt-1 flex gap-3 text-xs">
                  {item.incident_id !== null && (
                    <Link
                      className="font-medium text-accent-strong underline"
                      to={incidentHref(item.incident_id)}
                      onClick={() => {
                        setOpen(false);
                        if (item.read_at === null) markRead.mutate(item.id);
                      }}
                    >
                      Open {item.incident_id}
                    </Link>
                  )}
                  {item.read_at === null && (
                    <button
                      type="button"
                      className="text-muted underline"
                      onClick={() => {
                        markRead.mutate(item.id);
                      }}
                    >
                      Mark as read
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
