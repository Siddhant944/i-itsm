import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { vi } from "vitest";

import type { Schemas } from "../api/client";
import { AuthProvider } from "../auth/AuthContext";
import { ToastProvider } from "../components/Toasts";
import { setToken } from "../lib/session";

type Responder = (body: unknown, url: URL) => unknown;
/** JSON to answer with, a ready Response, or a function of the request. */
type Handler = object | Responder;

export interface Call {
  method: string;
  path: string;
  body: unknown;
}

/** A canned error in the API's one error shape (blueprint §8). */
export function apiError(status: number, message: string, fieldErrors?: Record<string, string>) {
  return new Response(
    JSON.stringify({
      error: { code: "error", message, details: fieldErrors ? { field_errors: fieldErrors } : {} },
    }),
    { status, headers: { "Content-Type": "application/json" } },
  );
}

/**
 * Replace fetch with a table of "METHOD /path" → JSON (or a function of the request body).
 * Unknown calls answer 404 so a screen that asks for something unexpected fails loudly.
 */
export function mockApi(routes: Record<string, Handler>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const url = new URL(request.url);
      const path = url.pathname.replace(/^\/api/, "");
      const text = await request.text();
      const body: unknown = text === "" ? undefined : JSON.parse(text);
      calls.push({ method: request.method, path, body });
      const key = `${request.method} ${path}`;
      if (!(key in routes)) return apiError(404, `No mock for ${key}`);
      const handler = routes[key];
      const result: unknown =
        typeof handler === "function" ? (handler as Responder)(body, url) : handler;
      if (result instanceof Response) return result;
      return new Response(JSON.stringify(result), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

const PERMISSIONS: Record<Schemas["Role"], Schemas["Permission"][]> = {
  employee: [
    "incident:create",
    "incident:view_own",
    "incident:add_info",
    "incident:verify",
    "incident:cancel_own",
  ],
  technician: [
    "incident:create",
    "incident:view_own",
    "incident:add_info",
    "incident:verify",
    "incident:cancel_own",
    "incident:view_assigned",
    "incident:work",
    "incident:override_priority",
    "incident:override_category",
    "incident:confirm_duplicate",
    "workload:view_own",
  ],
  team_lead: [],
  administrator: [],
  it_manager: [],
};
PERMISSIONS.team_lead = [
  ...PERMISSIONS.technician,
  "incident:view_team",
  "incident:reassign",
  "workload:view_team",
];
PERMISSIONS.administrator = [
  ...PERMISSIONS.team_lead,
  "incident:view_all",
  "incident:cancel_any",
  "users:manage",
  "technicians:manage",
  "catalogue:manage",
  "sla:manage",
  "strategy:manage",
  "sla:view_violations",
  "reports:view",
  "audit:view",
  "audit:verify",
];
PERMISSIONS.it_manager = PERMISSIONS.administrator;

const PORTAL: Record<Schemas["Role"], string> = {
  employee: "employee",
  technician: "technician",
  team_lead: "technician",
  administrator: "admin",
  it_manager: "admin",
};

export function me(role: Schemas["Role"], id = 1): Schemas["MeResponse"] {
  return {
    id,
    email: `${role}@campus.edu`,
    full_name: `${role} person`,
    role,
    portal: PORTAL[role],
    active: true,
    escalation_level: null,
    permissions: PERMISSIONS[role],
    // Support staff belong to team 1 of BASE_ROUTES, whose members are users 3 and 4.
    technician:
      role === "technician" || role === "team_lead"
        ? { skills: ["networking"], experience_level: 2, available: true, team_id: 1 }
        : null,
    telegram_chat_id: null,
    telegram_available: false,
  };
}

export function incident(
  overrides: Partial<Schemas["IncidentResponse"]> = {},
): Schemas["IncidentResponse"] {
  return {
    id: "INC-2026-0001",
    title: "Wi-Fi down",
    description: "No signal in the library",
    status: "ASSIGNED",
    priority: "P2",
    priority_score: 12,
    priority_overridden: false,
    impact: 2,
    urgency: 2,
    service_id: 1,
    category_id: 1,
    reporter_id: 1,
    assignee_id: 3,
    parent_id: null,
    cancel_reason: null,
    escalation_level: 0,
    reopen_count: 0,
    duplicate_of: null,
    duplicate_count: 0,
    created_at: "2026-11-11T04:00:00Z",
    acknowledged_at: null,
    resolved_at: null,
    closed_at: null,
    notes: [],
    resolution: null,
    feedback: null,
    sla: {
      paused: false,
      responded_at: null,
      response_deadline: "2026-11-11T04:15:00Z",
      response_status: "on_track",
      resolution_deadline: "2026-11-11T06:00:00Z",
      resolution_status: "on_track",
    },
    ...overrides,
  };
}

/** The reads nearly every screen makes; tests add their own on top. */
export const BASE_ROUTES: Record<string, Handler> = {
  // §6.2: nothing looks like a duplicate unless a test says otherwise.
  "POST /incidents/similar": { provider: "tfidf", candidates: [] },
  "GET /incidents/INC-2026-0001/possible-duplicates": { provider: "tfidf", candidates: [] },
  "GET /incidents/INC-2026-0001/correlation": { hint: null, root_causes: [], impacted: [] },
  "GET /incidents/INC-2026-0001/risk": () => null,
  "GET /incidents/INC-2026-0001/suggested-resolution": { fixes: [], summary: null, source: null },
  "GET /catalogue/services": [
    {
      id: 1,
      name: "Campus Wi-Fi",
      criticality: 2,
      sla_tier: "silver",
      tier_overridden: false,
      required_skill_id: null,
      depends_on: [],
      active: true,
    },
  ],
  "GET /catalogue/categories": [
    {
      id: 1,
      name: "Network",
      required_skill_id: 1,
      keywords: ["wifi"],
      minimum_priority: null,
      active: true,
    },
  ],
  "GET /catalogue/skills": [{ id: 1, name: "networking" }],
  "GET /catalogue/teams": [{ id: 1, name: "Network Operations", lead_id: 4, member_ids: [3, 4] }],
  "GET /users/directory": [
    { id: 1, full_name: "Devika Rao", role: "employee" },
    { id: 3, full_name: "Arjun Menon", role: "technician" },
  ],
  "GET /notifications": { unread: 0, latest: [] },
};

interface Options {
  /** Signs this person in before rendering; omit for a signed-out visitor. */
  user?: Schemas["MeResponse"];
  routes?: Record<string, Handler>;
  path?: string;
}

/** Render a route table with every provider the app has. Returns the recorded API calls. */
export function renderRoutes(routeTable: RouteObject[], options: Options = {}) {
  const { user, routes = {}, path = "/" } = options;
  setToken(user === undefined ? null : "test-token");
  const calls = mockApi({
    ...BASE_ROUTES,
    ...(user === undefined ? {} : { "GET /auth/me": user }),
    ...routes,
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(routeTable, { initialEntries: [path] });
  const view = render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { ...view, calls, router };
}

/** Render one screen at "/" with every provider. */
export function renderPage(element: ReactElement, options: Options = {}) {
  return renderRoutes(
    [
      { path: "/", element },
      { path: "*", element: <p>navigated away</p> },
    ],
    options,
  );
}
