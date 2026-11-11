import { screen, within } from "@testing-library/react";
import { matchRoutes } from "react-router";
import { describe, expect, it } from "vitest";

import { routes } from "../App";
import type { Portal } from "../auth/portal";
import { me, renderRoutes } from "../test/utils";
import { NAVIGATION, PORTAL_HOME } from "./nav";

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
});
