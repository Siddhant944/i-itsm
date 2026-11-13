import { Suspense, useEffect, useRef, useState } from "react";
import { Navigate, NavLink, Outlet, useNavigate } from "react-router";

import { useAuth } from "../auth/AuthContext";
import { portalOf, type Portal } from "../auth/portal";
import { Button } from "../components/Button";
import { NotificationBell } from "../components/NotificationBell";
import { ErrorState, Skeleton } from "../components/States";
import { roleLabel } from "../lib/format";
import { incidentPath, NAVIGATION, PORTAL_HOME, PORTAL_TITLE, type NavItem } from "./nav";
import { useLive } from "../api/useLive";
import { useLiveState } from "../lib/live";
import { TelegramSettings } from "../components/TelegramSettings";

function useVisibleNav(portal: Portal): NavItem[] {
  const { can } = useAuth();
  return NAVIGATION[portal].filter((item) => item.permission === undefined || can(item.permission));
}

function UserMenu() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const [telegram, setTelegram] = useState(false);
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
          setTelegram(true);
        }}
      >
        Telegram alerts
      </Button>
      {telegram && (
        <TelegramSettings
          onClose={() => {
            setTelegram(false);
          }}
        />
      )}
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

/** P4.8: said once, quietly, while live updates are down; screens keep polling meanwhile. */
export function LiveBanner() {
  if (useLiveState() !== "reconnecting") return null;
  return (
    <p
      role="status"
      data-testid="live-banner"
      className="mb-4 rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs"
    >
      Live updates paused — reconnecting. Screens refresh every few seconds meanwhile.
    </p>
  );
}

/** P5.6: a screen's chunk is fetched the first time it opens; the frame stays put meanwhile. */
function Screen() {
  return (
    <Suspense fallback={<Skeleton rows={4} label="Loading the screen" />}>
      <Outlet />
    </Suspense>
  );
}

/**
 * WCAG 2.4.1: the first Tab stop on every portal page jumps past the navigation to the screen.
 * Hidden until focused. It moves focus itself rather than changing the URL's hash.
 */
function SkipLink() {
  return (
    <a
      href="#main-content"
      onClick={(event) => {
        event.preventDefault();
        document.getElementById("main-content")?.focus();
      }}
      className="sr-only rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-ink focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50"
    >
      Skip to main content
    </a>
  );
}

/** Employee: a top bar and one centred column. */
function TopBarLayout({ portal }: { portal: Portal }) {
  const items = useVisibleNav(portal);
  return (
    <div data-portal={portal} className="min-h-screen bg-page text-ink">
      <SkipLink />
      <header className="bg-nav text-nav-ink">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-3">
          <p className="mr-auto text-lg font-semibold lg:mr-0">I-ITSM {PORTAL_TITLE[portal]}</p>
          {/* P5.6: below 1024 px the links take a row of their own under the name and the bell,
              so none of the three is cut off. */}
          <nav
            aria-label="Main"
            className="order-last flex w-full flex-wrap gap-1 lg:order-none lg:w-auto lg:flex-1"
          >
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap ${isActive ? "bg-nav-active" : "hover:bg-white/10"}`
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
      <main id="main-content" tabIndex={-1} className="mx-auto max-w-4xl px-4 py-8 outline-none">
        <LiveBanner />
        <Screen />
      </main>
    </div>
  );
}

/**
 * Technician and Admin: a sidebar and a wide working area. Below 1024 px the sidebar folds into
 * a drawer behind a "Menu" button (P5.6), so a phone or a split screen keeps the working area.
 */
function SidebarLayout({ portal }: { portal: Portal }) {
  const items = useVisibleNav(portal);
  const groups = [...new Set(items.map((item) => item.group ?? ""))];
  const [menuOpen, setMenuOpen] = useState(false);
  const drawer = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    // Focus follows the drawer (WCAG 2.4.3): into its first link on opening, back to the Menu
    // button on closing, so a keyboard user is never left on a hidden link or on <body>.
    if (menuOpen) drawer.current?.querySelector<HTMLElement>("a")?.focus();
    else if (wasOpen.current) menuButton.current?.focus();
    wasOpen.current = menuOpen;
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    // Widening past the breakpoint shows the sidebar anyway; do not leave the page inert.
    // jsdom (the unit tests) has no matchMedia.
    const wide =
      typeof window.matchMedia === "function" ? window.matchMedia("(min-width: 1024px)") : null;
    const onWide = (event: MediaQueryListEvent) => {
      if (event.matches) setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    wide?.addEventListener("change", onWide);
    return () => {
      window.removeEventListener("keydown", onKey);
      wide?.removeEventListener("change", onWide);
    };
  }, [menuOpen]);
  const close = () => {
    setMenuOpen(false);
  };
  return (
    <div data-portal={portal} className="flex min-h-screen bg-page text-ink">
      <SkipLink />
      {menuOpen && (
        <div
          aria-hidden="true"
          data-testid="menu-backdrop"
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={close}
        />
      )}
      <aside
        ref={drawer}
        id="portal-nav"
        className={`${menuOpen ? "fixed inset-y-0 left-0 z-40 flex shadow-xl" : "hidden"} w-56 shrink-0 flex-col overflow-y-auto bg-nav text-nav-ink lg:static lg:flex lg:shadow-none`}
      >
        <p className="px-4 pt-5 pb-1 text-xs font-semibold tracking-widest uppercase opacity-70">
          I-ITSM
        </p>
        <p className="px-4 pb-4 text-base font-semibold">{PORTAL_TITLE[portal]}</p>
        <nav aria-label="Main" className="flex-1 space-y-4 px-2 pb-4">
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
                        onClick={close}
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
        <header className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2 border-b border-line bg-surface px-4 py-2.5 sm:px-6">
          <button
            ref={menuButton}
            type="button"
            className="mr-auto rounded-md border border-line px-3 py-1.5 text-sm font-medium lg:hidden"
            aria-expanded={menuOpen}
            aria-controls="portal-nav"
            onClick={() => {
              setMenuOpen((open) => !open);
            }}
          >
            Menu
          </button>
          <NotificationBell incidentHref={(id) => incidentPath(portal, id)} />
          <UserMenu />
        </header>
        {/* While the drawer is open the page behind it can be neither clicked nor tabbed to. */}
        <main
          id="main-content"
          tabIndex={-1}
          inert={menuOpen}
          className="min-w-0 flex-1 px-4 py-6 outline-none sm:px-6"
        >
          <LiveBanner />
          <Screen />
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
  // P4.8: pushes while signed in; tests drive the hook directly with a fake socket.
  useLive(user !== null && import.meta.env.MODE !== "test");
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
