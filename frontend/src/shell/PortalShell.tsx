import { Navigate, NavLink, Outlet, useNavigate } from "react-router";

import { useAuth } from "../auth/AuthContext";
import { portalOf, type Portal } from "../auth/portal";
import { Button } from "../components/Button";
import { NotificationBell } from "../components/NotificationBell";
import { ErrorState, Skeleton } from "../components/States";
import { roleLabel } from "../lib/format";
import { incidentPath, NAVIGATION, PORTAL_HOME, PORTAL_TITLE, type NavItem } from "./nav";

function useVisibleNav(portal: Portal): NavItem[] {
  const { can } = useAuth();
  return NAVIGATION[portal].filter((item) => item.permission === undefined || can(item.permission));
}

function UserMenu() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  if (user === null) return null;
  return (
    <div className="flex items-center gap-3 text-sm">
      <div className="text-right leading-tight">
        <p className="font-medium" data-testid="current-user">
          {user.full_name}
        </p>
        <p className="text-xs opacity-75">{roleLabel(user.role)}</p>
      </div>
      <Button
        small
        onClick={() => {
          signOut();
          void navigate("/login");
        }}
      >
        Sign out
      </Button>
    </div>
  );
}

/** Employee: a top bar and one centred column. */
function TopBarLayout({ portal }: { portal: Portal }) {
  const items = useVisibleNav(portal);
  return (
    <div data-portal={portal} className="min-h-screen bg-page text-ink">
      <header className="bg-nav text-nav-ink">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center gap-4 px-4 py-3">
          <p className="text-lg font-semibold">I-ITSM {PORTAL_TITLE[portal]}</p>
          <nav aria-label="Main" className="flex flex-1 flex-wrap gap-1">
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? "bg-nav-active" : "hover:bg-white/10"}`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <NotificationBell incidentHref={(id) => incidentPath(portal, id)} />
          <UserMenu />
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}

/** Technician and Admin: a sidebar and a wide working area. */
function SidebarLayout({ portal }: { portal: Portal }) {
  const items = useVisibleNav(portal);
  const groups = [...new Set(items.map((item) => item.group ?? ""))];
  return (
    <div data-portal={portal} className="flex min-h-screen bg-page text-ink">
      <aside className="flex w-56 shrink-0 flex-col bg-nav text-nav-ink">
        <p className="px-4 pt-5 pb-1 text-xs font-semibold tracking-widest uppercase opacity-70">
          I-ITSM
        </p>
        <p className="px-4 pb-4 text-base font-semibold">{PORTAL_TITLE[portal]}</p>
        <nav aria-label="Main" className="flex-1 space-y-4 px-2">
          {groups.map((group) => (
            <div key={group}>
              {group !== "" && (
                <p className="px-2 pb-1 text-[11px] font-semibold tracking-wider uppercase opacity-60">
                  {group}
                </p>
              )}
              <ul className="space-y-0.5">
                {items
                  .filter((item) => (item.group ?? "") === group)
                  .map((item) => (
                    <li key={item.to}>
                      <NavLink
                        to={item.to}
                        className={({ isActive }) =>
                          `block rounded-md px-2 py-1.5 text-sm ${isActive ? "bg-nav-active font-semibold text-white" : "hover:bg-white/10"}`
                        }
                      >
                        {item.label}
                      </NavLink>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-end gap-4 border-b border-line bg-surface px-6 py-2.5">
          <NotificationBell incidentHref={(id) => incidentPath(portal, id)} />
          <UserMenu />
        </header>
        <main className="min-w-0 flex-1 px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

/** Shown while the stored session is checked, or when the API cannot be reached to check it. */
function SessionCheck() {
  const { status, problem, retry } = useAuth();
  return (
    <div className="mx-auto max-w-md p-10">
      {status === "unavailable" ? (
        <ErrorState error={problem} onRetry={retry} />
      ) : (
        <Skeleton rows={3} label="Signing you in" />
      )}
    </div>
  );
}

/**
 * The frame of one portal. Someone signed out goes to the sign-in page; someone signed in to a
 * different portal is sent to their own. This is navigation, not security: the API checks the
 * role on every call (blueprint §8).
 */
export function PortalShell({ portal }: { portal: Portal }) {
  const { status, user } = useAuth();
  if (status === "loading" || status === "unavailable") return <SessionCheck />;
  if (user === null) return <Navigate to="/login" replace />;
  const own = portalOf(user);
  if (own !== portal) return <Navigate to={PORTAL_HOME[own]} replace />;
  return portal === "employee" ? (
    <TopBarLayout portal={portal} />
  ) : (
    <SidebarLayout portal={portal} />
  );
}

/** "/" and unknown paths: the caller's own portal, or the sign-in page. */
export function HomeRedirect() {
  const { status, user } = useAuth();
  if (status === "loading" || status === "unavailable") return <SessionCheck />;
  if (user === null) return <Navigate to="/login" replace />;
  return <Navigate to={PORTAL_HOME[portalOf(user)]} replace />;
}
