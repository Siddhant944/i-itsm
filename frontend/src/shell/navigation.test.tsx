import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { matchRoutes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { routes } from "../App";
import type { Portal } from "../auth/portal";
import { apiError, me, renderRoutes } from "../test/utils";
import { NAVIGATION, PORTAL_HOME } from "./nav";
import { RouteError } from "./RouteError";

const PORTALS: Portal[] = ["employee", "technician", "admin"];

/** Every concrete path under a portal in the route table, e.g. "/admin/config/sla". */
function screensOf(portal: Portal): string[] {
  const root = routes.find((route) => route.path === `/${portal}`);
  return (root?.children ?? [])
    .map((child) => child.path)
    .filter((path): path is string => path !== undefined && !path.includes(":"))
    .map((path) => `/${portal}/${path}`);
}

describe("navigation", () => {
  it.each(PORTALS)("links every screen of the %s portal", (portal) => {
    const linked = NAVIGATION[portal].map((item) => item.to).sort();
    expect(linked).toEqual(screensOf(portal).sort());
  });

  it.each(PORTALS)("every %s link and the portal home lead to a real route", (portal) => {
    for (const path of [...NAVIGATION[portal].map((item) => item.to), PORTAL_HOME[portal]]) {
      const matched = matchRoutes(routes, path);
      expect(matched?.at(-1)?.route.path, path).not.toBe("*");
    }
  });
});

const QUEUE = { "GET /incidents/queue": [], "GET /incidents/mine": [] };

describe("the three portals", () => {
  it("sends a signed-out visitor to the sign-in page", async () => {
    renderRoutes(routes, { path: "/admin/users" });
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("does not sign someone out because the API is unreachable", async () => {
    const { router } = renderRoutes(routes, {
      user: me("employee"),
      routes: { "GET /auth/me": apiError(503, "The database is unavailable.") },
      path: "/employee/incidents",
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("The database is unavailable.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/employee/incidents");
    expect(window.sessionStorage.getItem("iitsm.token")).toBe("test-token");
  });

  it("signs someone out when the API says the token is no longer good", async () => {
    renderRoutes(routes, {
      user: me("employee"),
      routes: { "GET /auth/me": apiError(401, "Sign in to continue.") },
      path: "/employee/incidents",
    });
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("iitsm.token")).toBeNull();
  });

  it("gives an employee a top bar with their two screens", async () => {
    const { container } = renderRoutes(routes, { user: me("employee"), routes: QUEUE, path: "/" });
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["My incidents", "Report an incident"]);
    expect(container.querySelector("[data-portal]")).toHaveAttribute("data-portal", "employee");
    expect(screen.getByTestId("current-user")).toHaveTextContent("employee person");
  });

  it("hides the team queue from a technician and shows it to a team lead", async () => {
    const first = renderRoutes(routes, { user: me("technician", 3), routes: QUEUE, path: "/" });
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("link", { name: "Team queue" })).not.toBeInTheDocument();
    expect(first.container.querySelector("[data-portal]")).toHaveAttribute(
      "data-portal",
      "technician",
    );
    first.unmount();

    renderRoutes(routes, { user: me("team_lead", 4), routes: QUEUE, path: "/" });
    const leadNav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(leadNav).getByRole("link", { name: "Team queue" })).toBeInTheDocument();
  });

  it("keeps someone out of a portal that is not theirs", async () => {
    const { router } = renderRoutes(routes, {
      user: me("employee"),
      routes: QUEUE,
      path: "/admin/users",
    });
    expect(await screen.findByRole("heading", { name: "My incidents" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/employee/incidents");
  });

  it("gives an administrator every operations and configuration screen", async () => {
    const { container } = renderRoutes(routes, {
      user: me("administrator", 8),
      routes: { "GET /users": [] },
      path: "/admin/users",
    });
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link")).toHaveLength(NAVIGATION.admin.length);
    expect(container.querySelector("[data-portal]")).toHaveAttribute("data-portal", "admin");
  });

  it("folds the sidebar into a drawer on narrow screens (P5.6)", async () => {
    const user = userEvent.setup();
    const { router } = renderRoutes(routes, {
      user: me("technician", 3),
      routes: QUEUE,
      path: "/technician/queue",
    });
    const menu = await screen.findByRole("button", { name: "Menu" });
    expect(menu).toHaveAttribute("aria-controls", "portal-nav");
    expect(menu).toHaveAttribute("aria-expanded", "false");

    await user.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    const nav = screen.getByRole("navigation", { name: "Main" });
    // Focus moves into the drawer, and the page behind it is out of reach.
    expect(within(nav).getAllByRole("link")[0]).toHaveFocus();
    expect(screen.getByRole("main", { hidden: true })).toHaveAttribute("inert");
    await user.keyboard("{Escape}");
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(menu).toHaveFocus();
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");

    await user.click(menu);
    await user.click(within(nav).getByRole("link", { name: "Workload" }));
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(router.state.location.pathname).toBe("/technician/workload");
  });

  it("offers a reload when a screen cannot be opened (P5 review)", async () => {
    const user = userEvent.setup();
    const reload = vi.fn();
    vi.stubGlobal("location", { href: window.location.href, reload });
    function Broken(): never {
      throw new Error("Failed to fetch dynamically imported module");
    }
    renderRoutes([{ path: "/", element: <Broken />, errorElement: <RouteError /> }]);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This screen could not be opened");
    await user.click(within(alert).getByRole("button", { name: "Reload" }));
    expect(reload).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });
});
