import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { apiError, incident, me, renderPage, renderRoutes } from "../test/utils";
import { AuditPage } from "./admin/AuditPage";
import { AssignmentPage } from "./admin/config/AssignmentPage";
import { CategoriesPage } from "./admin/config/CategoriesPage";
import { SLAPage } from "./admin/config/SLAPage";
import { UsersPage } from "./admin/UsersPage";
import { SearchPage } from "./admin/SearchPage";
import { LoginPage } from "./auth/LoginPage";
import { RegisterPage } from "./auth/RegisterPage";
import { MyIncidentsPage } from "./employee/MyIncidentsPage";
import { ReportPage } from "./employee/ReportPage";
import { IncidentDetailPage } from "./incident/IncidentDetailPage";
import { QueuePage } from "./technician/QueuePage";

const TOKEN = {
  access_token: "t",
  token_type: "bearer",
  expires_in: 1800,
  user_id: 1,
  role: "employee",
  portal: "employee",
  full_name: "Devika Rao",
};

function detail(options: Parameters<typeof renderRoutes>[1]) {
  return renderRoutes(
    [
      { path: "/employee/incidents/:id", element: <IncidentDetailPage /> },
      { path: "*", element: <p>elsewhere</p> },
    ],
    { path: "/employee/incidents/INC-2026-0001", ...options },
  );
}

describe("sign-in and registration", () => {
  it("explains a refused sign-in without saying which part was wrong (D-019)", async () => {
    renderPage(<LoginPage />, {
      routes: { "POST /auth/login": apiError(401, "Invalid email or password.") },
    });
    await userEvent.type(screen.getByLabelText("Email"), "a@campus.edu");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("locked for 15 minutes");
  });

  it("signs in and moves to the caller's own portal", async () => {
    const { router } = renderRoutes(
      [
        { path: "/login", element: <LoginPage /> },
        { path: "/employee/incidents", element: <p>my portal</p> },
      ],
      {
        path: "/login",
        routes: { "POST /auth/login": TOKEN, "GET /auth/me": me("employee") },
      },
    );
    await userEvent.type(screen.getByLabelText("Email"), "employee@campus.edu");
    await userEvent.type(screen.getByLabelText("Password"), "demo1234");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("my portal")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/employee/incidents");
    expect(window.sessionStorage.getItem("iitsm.token")).toBe("t");
  });

  it("puts a registration problem beside the field it belongs to", async () => {
    renderPage(<RegisterPage />, {
      routes: {
        "POST /auth/register": apiError(422, "Some fields are invalid.", {
          email: "An account with this email already exists.",
        }),
      },
    });
    await userEvent.type(screen.getByLabelText("Full name"), "Asha");
    await userEvent.type(screen.getByLabelText("Email"), "asha@campus.edu");
    await userEvent.type(screen.getByLabelText("Password"), "long enough");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("the employee portal", () => {
  it("lists what the person reported, or invites a first report", async () => {
    const first = renderPage(<MyIncidentsPage />, {
      user: me("employee"),
      routes: { "GET /incidents/mine": [] },
    });
    expect(await screen.findByText("You have not reported anything yet")).toBeInTheDocument();
    first.unmount();

    renderPage(<MyIncidentsPage />, {
      user: me("employee"),
      routes: { "GET /incidents/mine": [incident()] },
    });
    const table = await screen.findByRole("table", { name: "My incidents" });
    expect(within(table).getByText("Wi-Fi down")).toBeInTheDocument();
    expect(within(table).getByText("P2 High")).toBeInTheDocument();
    expect(await within(table).findByText("Arjun Menon")).toBeInTheDocument();
  });

  it("shows a load failure with a way to retry", async () => {
    renderPage(<MyIncidentsPage />, {
      user: me("employee"),
      routes: { "GET /incidents/mine": apiError(503, "The database is unavailable.") },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("The database is unavailable.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("shows the AI's category with its confidence and applies it only when asked", async () => {
    const { calls } = renderPage(<ReportPage />, {
      user: me("employee"),
      routes: {
        "POST /incidents/classify": { category_id: 1, confidence: 0.82, source: "rules" },
        "POST /incidents": {
          incident: incident(),
          suggestion: null,
          assignment: null,
          needs_triage: false,
          queued_for_team_lead: false,
        },
      },
    });
    const submit = await screen.findByRole("button", { name: "Submit incident" });
    expect(submit).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/one line/), "Wifi keeps dropping");
    await userEvent.type(screen.getByLabelText("What happened?"), "No signal in the library");
    const suggestion = await screen.findByTestId("ai-suggestion", {}, { timeout: 3000 });
    expect(suggestion).toHaveTextContent("Suggested category: Network");
    expect(suggestion).toHaveTextContent("High confidence · 82%");
    // Nothing is applied silently: the select still says the help desk decides.
    expect(screen.getByLabelText("Category")).toHaveValue("");

    await userEvent.click(within(suggestion).getByRole("button", { name: "Use this suggestion" }));
    expect(screen.getByLabelText("Category")).toHaveValue("1");
    expect(suggestion).toHaveTextContent("Applied");
    // ...and it can be overridden again.
    await userEvent.selectOptions(screen.getByLabelText("Category"), "");

    await userEvent.selectOptions(screen.getByLabelText(/Which service/), "1");
    await userEvent.click(screen.getByLabelText("Just me"));
    await userEvent.click(screen.getByLabelText("I am blocked"));
    await userEvent.click(submit);

    await waitFor(() => {
      expect(calls.find((c) => c.method === "POST" && c.path === "/incidents")?.body).toEqual({
        title: "Wifi keeps dropping",
        description: "No signal in the library",
        service_id: 1,
        impact: 1,
        urgency: 3,
        category_id: null,
        follow: null,
      });
    });
    expect(await screen.findByText(/INC-2026-0001 reported as P2/)).toBeInTheDocument();
  });

  it("drops a suggestion as soon as the text it was made for changes", async () => {
    renderPage(<ReportPage />, {
      user: me("employee"),
      routes: {
        "POST /incidents/classify": (body: unknown) =>
          // Only the wifi text gets a suggestion; the rewritten one fails to classify.
          JSON.stringify(body).includes("printer")
            ? apiError(503, "Classifier unavailable.")
            : { category_id: 1, confidence: 0.82, source: "rules" },
      },
    });
    await userEvent.type(await screen.findByLabelText(/one line/), "Wifi keeps dropping");
    expect(await screen.findByTestId("ai-suggestion", {}, { timeout: 3000 })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("What happened?"), "Actually it is the printer");
    // Gone at once, not after the next answer arrives - and it stays gone when that one fails.
    expect(screen.queryByTestId("ai-suggestion")).not.toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 900));
    expect(screen.queryByTestId("ai-suggestion")).not.toBeInTheDocument();
  });

  it("tells the reporter which category was applied when they left it blank", async () => {
    renderPage(<ReportPage />, {
      user: me("employee"),
      routes: {
        "POST /incidents/classify": apiError(503, "Classifier unavailable."),
        "POST /incidents": {
          incident: incident(),
          suggestion: { category_id: 1, confidence: 0.5, source: "rules" },
          assignment: null,
          needs_triage: false,
          queued_for_team_lead: false,
        },
      },
    });
    await userEvent.type(await screen.findByLabelText(/one line/), "Wifi keeps dropping");
    await userEvent.type(screen.getByLabelText("What happened?"), "No signal in the library");
    await userEvent.selectOptions(screen.getByLabelText(/Which service/), "1");
    await userEvent.click(screen.getByLabelText("Just me"));
    await userEvent.click(screen.getByLabelText("I am blocked"));
    await userEvent.click(screen.getByRole("button", { name: "Submit incident" }));
    expect(
      await screen.findByText(
        "Classified automatically as Network (medium confidence, 50%). The help desk can change it.",
      ),
    ).toBeInTheDocument();
  });

  it("asks the reporter to confirm a fix, and sends the rating", async () => {
    const resolved = incident({
      status: "RESOLVED",
      resolution: {
        resolver_id: 3,
        resolved_at: "2026-11-11T05:00:00Z",
        summary: "Rebooted the AP",
      },
    });
    const { calls } = detail({
      user: me("employee", 1),
      routes: {
        "GET /incidents/INC-2026-0001": resolved,
        "POST /incidents/INC-2026-0001/verify": { ...resolved, status: "VERIFIED" },
      },
    });
    expect(await screen.findByText("A fix has been applied. Is it working for you?")).toBeVisible();
    expect(screen.getAllByText("Rebooted the AP").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Yes, confirm the fix" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm the fix" });
    expect(within(dialog).getByRole("button", { name: "Confirm and rate" })).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("button", { name: "4 out of 5" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm and rate" }));
    await waitFor(() => {
      expect(calls.find((c) => c.path.endsWith("/verify"))?.body).toEqual({
        rating: 4,
        comment: "",
      });
    });
    expect(await screen.findByText("Verified")).toBeInTheDocument();
  });

  it("shows the technician's question and sends the reply", async () => {
    const base = incident();
    const waiting = incident({
      status: "ON_HOLD",
      sla: base.sla === null ? null : { ...base.sla, paused: true },
      notes: [
        {
          author_id: 3,
          created_at: "2026-11-11T04:20:00Z",
          kind: "info_request",
          text: "Which floor?",
        },
      ],
    });
    const { calls } = detail({
      user: me("employee", 1),
      routes: {
        "GET /incidents/INC-2026-0001": waiting,
        "POST /incidents/INC-2026-0001/information": { ...waiting, status: "IN_PROGRESS" },
      },
    });
    expect(await screen.findByText("The technician needs more information from you")).toBeVisible();
    expect(screen.getByTestId("sla-chip")).toHaveTextContent("SLA paused");
    await userEvent.type(screen.getByLabelText("Your message"), "First floor");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => {
      expect(calls.find((c) => c.path.endsWith("/information"))?.body).toEqual({
        text: "First floor",
      });
    });
  });
});

describe("the technician portal", () => {
  it("orders the queue by urgency", async () => {
    renderPage(<QueuePage />, {
      user: me("technician", 3),
      routes: {
        "GET /incidents/queue": [
          incident({ id: "INC-2026-0002", title: "Printer jam", priority: "P4" }),
          incident({ id: "INC-2026-0003", title: "Portal down", priority: "P1" }),
        ],
      },
    });
    const table = await screen.findByRole("table", { name: "My queue" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Portal down");
    expect(rows[1]).toHaveTextContent("Printer jam");
  });

  it("offers the assignee the next legal step and shows the API's refusal", async () => {
    const { calls } = detail({
      user: me("technician", 3),
      routes: {
        "GET /incidents/INC-2026-0001": incident(),
        "POST /incidents/INC-2026-0001/acknowledge": apiError(
          409,
          "An incident that is ASSIGNED cannot be acknowledged twice.",
        ),
      },
    });
    const actions = await screen.findByTestId("actions");
    expect(within(actions).getByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    expect(within(actions).queryByRole("button", { name: "Resolve" })).not.toBeInTheDocument();
    await userEvent.click(within(actions).getByRole("button", { name: "Acknowledge" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("cannot be acknowledged twice");
    expect(calls.some((c) => c.path.endsWith("/acknowledge"))).toBe(true);
  });

  it("requires a reason to override a priority", async () => {
    const { calls } = detail({
      user: me("technician", 3),
      routes: {
        "GET /incidents/INC-2026-0001": incident(),
        "POST /incidents/INC-2026-0001/priority": incident({
          priority: "P1",
          priority_overridden: true,
        }),
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Override priority" }));
    const dialog = screen.getByRole("dialog");
    const save = within(dialog).getByRole("button", { name: "Override priority" });
    expect(save).toBeDisabled();
    await userEvent.selectOptions(within(dialog).getByLabelText("New priority"), "P1");
    await userEvent.type(within(dialog).getByLabelText("Reason"), "Exam week");
    await userEvent.click(save);
    await waitFor(() => {
      expect(calls.find((c) => c.path.endsWith("/priority"))?.body).toEqual({
        priority: "P1",
        reason: "Exam week",
      });
    });
    expect(await screen.findByText("Priority overridden")).toBeInTheDocument();
  });

  it("shows a team lead the ranked candidates with their reasons", async () => {
    detail({
      user: me("team_lead", 4),
      routes: {
        "GET /incidents/INC-2026-0001": incident(),
        "GET /incidents/INC-2026-0001/assignment-advice": {
          strategy: "smart",
          ranked: [
            {
              technician_id: 3,
              score: 0.82,
              reasons: ["1/1 skills", "60 % capacity free", "senior"],
            },
          ],
        },
      },
    });
    const candidate = await screen.findByTestId("candidate");
    expect(candidate).toHaveTextContent("Arjun Menon");
    expect(candidate).toHaveTextContent("Score 0.82 · 1/1 skills · 60 % capacity free · senior");
    expect(within(candidate).getByText("Current")).toBeInTheDocument();
    expect(screen.getByText("Smart")).toBeInTheDocument();
  });
});

const ADMIN = me("administrator", 8);

describe("the admin portal", () => {
  it("adds a category and tells the admin it is live", async () => {
    const created = {
      id: 2,
      name: "Printing",
      required_skill_id: null,
      keywords: ["printer", "toner"],
      minimum_priority: "P3",
      active: true,
    };
    const { calls } = renderPage(<CategoriesPage />, {
      user: ADMIN,
      routes: { "POST /catalogue/categories": created },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Add a category" }));
    const dialog = screen.getByRole("dialog", { name: "Add a category" });
    await userEvent.type(within(dialog).getByLabelText("Name"), "Printing");
    await userEvent.type(within(dialog).getByLabelText("Keywords"), "printer, toner");
    await userEvent.selectOptions(within(dialog).getByLabelText("Minimum priority"), "P3");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add category" }));
    await waitFor(() => {
      expect(
        calls.find((c) => c.method === "POST" && c.path === "/catalogue/categories")?.body,
      ).toEqual({
        name: "Printing",
        required_skill_id: null,
        keywords: ["printer", "toner"],
        minimum_priority: "P3",
        active: true,
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent("live for the next incident");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the dialog open and names the field when a category is refused", async () => {
    renderPage(<CategoriesPage />, {
      user: ADMIN,
      routes: {
        "POST /catalogue/categories": apiError(422, "Some fields are invalid.", {
          name: "This name is already in use.",
        }),
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Add a category" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Name"), "Network");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add category" }));
    expect(await within(dialog).findByText("This name is already in use.")).toBeInTheDocument();
  });

  it("edits one cell of the SLA grid and refuses an impossible target", async () => {
    const cell = { tier: "gold", priority: "P1", response_minutes: 5, resolution_minutes: 30 };
    const { calls } = renderPage(<SLAPage />, {
      user: ADMIN,
      routes: {
        "GET /sla/policies": [cell],
        "PUT /sla/policies/gold/P1": { ...cell, response_minutes: 3 },
      },
    });
    const response = await screen.findByLabelText("Gold P1 response minutes");
    expect(screen.queryByRole("button", { name: "Save Gold P1" })).not.toBeInTheDocument();
    await userEvent.clear(response);
    await userEvent.type(response, "45");
    expect(screen.getByRole("button", { name: "Save Gold P1" })).toBeDisabled();
    await userEvent.clear(response);
    await userEvent.type(response, "3");
    await userEvent.click(screen.getByRole("button", { name: "Save Gold P1" }));
    await waitFor(() => {
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        response_minutes: 3,
        resolution_minutes: 30,
      });
    });
    expect(screen.getAllByText(/Not set/)).toHaveLength(11);
  });

  it("switches the assignment strategy", async () => {
    const settings = {
      strategy: "smart",
      weights: { skills: 0.4, capacity: 0.3, experience: 0.15, history: 0.15 },
      available: ["load_based", "skill_based", "smart"],
    };
    const { calls } = renderPage(<AssignmentPage />, {
      user: ADMIN,
      routes: {
        "GET /config/assignment": settings,
        "PUT /config/assignment": { ...settings, strategy: "load_based" },
      },
    });
    expect(await screen.findByTestId("weights-total")).toHaveTextContent("Total 100%");
    await userEvent.click(screen.getByRole("radio", { name: /Load based/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save assignment settings" }));
    await waitFor(() => {
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        strategy: "load_based",
        weights: settings.weights,
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Load based strategy is active");
  });

  it("saves a role and a technician profile as one change", async () => {
    const employee = {
      id: 1,
      email: "devika@campus.edu",
      full_name: "Devika Rao",
      role: "employee",
      active: true,
      skills: null,
      experience_level: null,
      available: null,
      team_id: null,
    };
    const { calls } = renderPage(<UsersPage />, {
      user: ADMIN,
      routes: {
        "GET /users": [employee],
        "PATCH /users/1": { ...employee, role: "technician", skills: ["networking"] },
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Devika Rao" });
    await userEvent.selectOptions(within(dialog).getByLabelText("Role"), "technician");
    await userEvent.click(await within(dialog).findByRole("button", { name: "networking" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => {
      expect(calls.filter((c) => c.method !== "GET")).toEqual([
        {
          method: "PATCH",
          path: "/users/1",
          body: {
            role: "technician",
            technician: {
              skills: ["networking"],
              experience_level: 1,
              available: true,
              team_id: null,
            },
          },
        },
      ]);
    });
  });

  const record = {
    sequence: 12,
    occurred_at: "2026-11-11T04:00:00Z",
    action: "incident.state_changed",
    actor_id: 3,
    incident_id: "INC-2026-0001",
    details: { from: "ASSIGNED", to: "ACKNOWLEDGED" },
    hash: "abcdef0123456789",
  };
  const page = { items: [record], total: 12, limit: 50, offset: 0 };

  it("BR-10 reports an intact audit chain", async () => {
    renderPage(<AuditPage />, {
      user: ADMIN,
      routes: {
        "GET /audit": page,
        "POST /audit/verify": {
          intact: true,
          checked: 12,
          broken_at: null,
          summary: "12 audit records verified; the chain is intact.",
        },
      },
    });
    const table = await screen.findByRole("table", { name: "Audit log" });
    expect(within(table).getByText("Incident state changed")).toBeInTheDocument();
    expect(within(table).getByText("from: ASSIGNED · to: ACKNOWLEDGED")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Verify integrity" }));
    expect(await screen.findByTestId("integrity-result")).toHaveTextContent(
      "✓ 12 audit records verified",
    );
  });

  it("BR-10 reports where the chain breaks after tampering", async () => {
    renderPage(<AuditPage />, {
      user: ADMIN,
      routes: {
        "GET /audit": page,
        "POST /audit/verify": {
          intact: false,
          checked: 12,
          broken_at: 4,
          summary: "The audit chain breaks at record 4 of 12.",
        },
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Verify integrity" }));
    const result = await screen.findByTestId("integrity-result");
    expect(result).toHaveTextContent("✗ The audit chain breaks at record 4 of 12.");
    expect(result.className).toContain("red");
  });

  it("searches with the chosen filters and pages through the result", async () => {
    const found = {
      items: [incident()],
      total: 40,
      limit: 25,
      offset: 0,
      page_number: 1,
      page_count: 2,
      has_more: true,
    };
    const { calls } = renderPage(<SearchPage />, {
      user: ADMIN,
      routes: { "POST /incidents/search": found },
    });
    expect(await screen.findByTestId("result-count")).toHaveTextContent(
      "40 incidents · page 1 of 2",
    );
    await userEvent.click(screen.getByRole("button", { name: "P1 Critical" }));
    await userEvent.click(screen.getByRole("button", { name: "Breached" }));
    await userEvent.type(screen.getByLabelText("Text"), "wifi");
    await userEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => {
      expect(screen.getByTestId("active-filters")).toHaveTextContent("3 filters applied");
    });
    const searches = () => calls.filter((c) => c.path === "/incidents/search");
    expect(searches().at(-1)?.body).toMatchObject({
      text: "wifi",
      priorities: ["P1"],
      sla_statuses: ["breached"],
      offset: 0,
    });
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => {
      expect(searches().at(-1)?.body).toMatchObject({ offset: 25, text: "wifi" });
    });
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("says so when nothing matches", async () => {
    renderPage(<SearchPage />, {
      user: ADMIN,
      routes: {
        "POST /incidents/search": {
          items: [],
          total: 0,
          limit: 25,
          offset: 0,
          page_number: 1,
          page_count: 0,
          has_more: false,
        },
      },
    });
    expect(await screen.findByText("No incidents match these filters")).toBeInTheDocument();
  });
});

describe("duplicates (§6.2, BR-09)", () => {
  const lookalike = {
    id: "INC-2026-0040",
    title: "Fee portal down",
    status: "ASSIGNED",
    created_at: "2026-11-06T08:50:00Z",
    score: 0.81,
    reasons: ["text 64 % alike", "same service", "reported close together"],
  };

  it("offers a similar open incident while typing, and follows it only when asked", async () => {
    const { calls } = renderPage(<ReportPage />, {
      user: me("employee"),
      routes: {
        "POST /incidents/classify": apiError(503, "Classifier unavailable."),
        "POST /incidents/similar": { provider: "tfidf", candidates: [lookalike] },
        "POST /incidents": {
          incident: incident({ status: "CANCELLED", cancel_reason: "duplicate" }),
          suggestion: null,
          assignment: null,
          needs_triage: false,
          queued_for_team_lead: false,
          possible_duplicates: [lookalike],
          followed: { id: "INC-2026-0040", title: "Fee portal down", status: "ASSIGNED" },
        },
      },
    });
    await userEvent.type(await screen.findByLabelText(/one line/), "Fee payment portal error");
    const hint = await screen.findByTestId("similar-incidents", {}, { timeout: 3000 });
    expect(hint).toHaveTextContent("INC-2026-0040");
    expect(hint).toHaveTextContent("81% match");
    expect(hint).toHaveTextContent("same service");

    await userEvent.type(screen.getByLabelText("What happened?"), "Cannot pay");
    await userEvent.selectOptions(screen.getByLabelText(/Which service/), "1");
    await userEvent.click(screen.getByLabelText("Just me"));
    await userEvent.click(screen.getByLabelText("I am blocked"));
    // Typing changed the text, so the hint is recomputed for it before it can be followed.
    const fresh = await screen.findByTestId("similar-incidents", {}, { timeout: 3000 });
    await userEvent.click(within(fresh).getByRole("button", { name: "Follow this instead" }));
    await userEvent.click(screen.getByRole("button", { name: "Follow INC-2026-0040" }));

    await waitFor(() => {
      const sent = calls.find((c) => c.method === "POST" && c.path === "/incidents")?.body;
      expect(sent).toMatchObject({ follow: "INC-2026-0040" });
    });
    expect(await screen.findByText(/You are following INC-2026-0040/)).toBeInTheDocument();
  });

  it("explains a refused repeat and links to the first report", async () => {
    renderPage(<ReportPage />, {
      user: me("employee"),
      routes: {
        "POST /incidents/classify": apiError(503, "Classifier unavailable."),
        "POST /incidents": () =>
          new Response(
            JSON.stringify({
              error: {
                code: "duplicate_incident",
                message: "This looks like INC-2026-0040, which you reported recently.",
                details: { existing_incident_id: "INC-2026-0040" },
              },
            }),
            { status: 409, headers: { "Content-Type": "application/json" } },
          ),
      },
    });
    await userEvent.type(await screen.findByLabelText(/one line/), "Fee portal down");
    await userEvent.type(screen.getByLabelText("What happened?"), "Error 503");
    await userEvent.selectOptions(screen.getByLabelText(/Which service/), "1");
    await userEvent.click(screen.getByLabelText("Just me"));
    await userEvent.click(screen.getByLabelText("I am blocked"));
    await userEvent.click(screen.getByRole("button", { name: "Submit incident" }));
    const refused = await screen.findByTestId("repeat-report");
    expect(refused).toHaveTextContent("You reported this a few minutes ago.");
    expect(within(refused).getByRole("link", { name: "INC-2026-0040" })).toHaveAttribute(
      "href",
      "/employee/incidents/INC-2026-0040",
    );
  });

  it("lets the technician confirm a possible duplicate, in two clicks", async () => {
    const { calls } = renderRoutes(
      [{ path: "/technician/incidents/:id", element: <IncidentDetailPage /> }],
      {
        path: "/technician/incidents/INC-2026-0001",
        user: me("technician", 3),
        routes: {
          "GET /incidents/INC-2026-0001": incident(),
          "GET /incidents/INC-2026-0001/possible-duplicates": {
            provider: "tfidf",
            candidates: [lookalike],
          },
          "POST /incidents/INC-2026-0001/confirm-duplicate": incident({
            status: "CANCELLED",
            cancel_reason: "duplicate",
            parent_id: "INC-2026-0040",
          }),
        },
      },
    );
    const found = await screen.findByTestId("possible-duplicate");
    expect(found).toHaveTextContent("Fee portal down");
    expect(found).toHaveTextContent("81% match");
    await userEvent.click(within(found).getByRole("button", { name: "Confirm duplicate…" }));
    await userEvent.click(
      within(found).getByRole("button", { name: "Cancel INC-2026-0001 as its duplicate" }),
    );
    await waitFor(() => {
      expect(calls.find((c) => c.path.endsWith("/confirm-duplicate"))?.body).toEqual({
        parent_id: "INC-2026-0040",
      });
    });
  });

  it("tells a follower what their report is linked to, without a link they cannot open", async () => {
    detail({
      user: me("employee", 1),
      routes: {
        "GET /incidents/INC-2026-0001": incident({
          status: "CANCELLED",
          cancel_reason: "duplicate",
          parent_id: "INC-2026-0040",
          duplicate_of: { id: "INC-2026-0040", title: "Fee portal down", status: "IN_PROGRESS" },
        }),
      },
    });
    const banner = await screen.findByTestId("linked-duplicate");
    expect(banner).toHaveTextContent("same problem as INC-2026-0040 (Fee portal down)");
    expect(banner).toHaveTextContent("we will tell you when it is fixed");
    expect(screen.queryByRole("link", { name: "INC-2026-0040" })).not.toBeInTheDocument();
    expect(screen.queryByText("Possible duplicates")).not.toBeInTheDocument();
  });
});

describe("correlation (§6.2)", () => {
  it("shows the technician the likely root cause and the way the services connect", async () => {
    renderRoutes([{ path: "/technician/incidents/:id", element: <IncidentDetailPage /> }], {
      path: "/technician/incidents/INC-2026-0001",
      user: me("technician", 3),
      routes: {
        "GET /incidents/INC-2026-0001": incident(),
        "GET /incidents/INC-2026-0001/correlation": {
          hint: "Likely related to INC-2026-0040 (Database Cluster): possible root cause.",
          root_causes: [
            {
              id: "INC-2026-0040",
              title: "Database cluster unreachable",
              status: "IN_PROGRESS",
              priority: "P1",
              service_id: 4,
              service_name: "Database Cluster",
              hops: 1,
              path: ["Fee Payment Portal", "Database Cluster"],
            },
          ],
          impacted: [],
        },
      },
    });
    expect(await screen.findByTestId("root-cause-hint")).toHaveTextContent(
      "Likely related to INC-2026-0040 (Database Cluster): possible root cause.",
    );
    const related = screen.getByTestId("related-incident");
    expect(related).toHaveTextContent("Fee Payment Portal → Database Cluster");
    expect(within(related).getByRole("link", { name: "INC-2026-0040" })).toHaveAttribute(
      "href",
      "/technician/incidents/INC-2026-0040",
    );
  });

  it("never asks for it in the employee portal (BR-01)", async () => {
    const { calls } = detail({
      user: me("employee", 1),
      routes: { "GET /incidents/INC-2026-0001": incident() },
    });
    expect(await screen.findByText("Wi-Fi down")).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/correlation"))).toBe(false);
  });
});

describe("predictive SLA risk (§6.3)", () => {
  it("shows the technician the predicted breach risk and the evidence behind it", async () => {
    renderRoutes([{ path: "/technician/incidents/:id", element: <IncidentDetailPage /> }], {
      path: "/technician/incidents/INC-2026-0001",
      user: me("technician", 3),
      routes: {
        "GET /incidents/INC-2026-0001": incident(),
        "GET /incidents/INC-2026-0001/risk": {
          at_risk: true,
          method: "history",
          probability: 0.62,
          samples: 13,
          reason:
            "62 % of past P2 Network incidents still open at 1 h 20 m went on to breach (8 of 13).",
        },
      },
    });
    expect(await screen.findByTestId("risk-chip")).toHaveTextContent("Breach risk 62%");
    expect(screen.getByTestId("risk-reason")).toHaveTextContent(
      "62 % of past P2 Network incidents still open at 1 h 20 m went on to breach",
    );
  });

  it("says when the 75 % rule answered for want of history", async () => {
    renderRoutes([{ path: "/technician/incidents/:id", element: <IncidentDetailPage /> }], {
      path: "/technician/incidents/INC-2026-0001",
      user: me("technician", 3),
      routes: {
        "GET /incidents/INC-2026-0001": incident(),
        "GET /incidents/INC-2026-0001/risk": {
          at_risk: false,
          method: "threshold",
          probability: null,
          samples: 3,
          reason: "40 % of the resolution target used; too few past P2 Network incidents (3).",
        },
      },
    });
    expect(await screen.findByTestId("risk-chip")).toHaveTextContent("On track (75 % rule)");
  });

  it("is not asked for in the employee portal", async () => {
    const { calls } = detail({
      user: me("employee", 1),
      routes: { "GET /incidents/INC-2026-0001": incident() },
    });
    expect(await screen.findByText("Wi-Fi down")).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/risk"))).toBe(false);
  });
});

describe("suggested resolution (§6.1)", () => {
  it("shows past fixes with the cited AI summary and copies a fix into the resolve box", async () => {
    const { calls } = renderRoutes(
      [{ path: "/technician/incidents/:id", element: <IncidentDetailPage /> }],
      {
        path: "/technician/incidents/INC-2026-0001",
        user: me("technician", 3),
        routes: {
          "GET /incidents/INC-2026-0001": incident({ status: "IN_PROGRESS" }),
          "GET /incidents/INC-2026-0001/suggested-resolution": {
            fixes: [
              {
                id: "INC-2026-0040",
                title: "Wifi drops in library",
                status: "CLOSED",
                resolution: "Rebooted access point AP-3",
                score: 0.71,
              },
            ],
            summary: "Reboot the library access point [INC-2026-0040].",
            source: "gemini",
          },
          "POST /incidents/INC-2026-0001/resolve": incident({ status: "RESOLVED" }),
        },
      },
    );
    expect(await screen.findByTestId("fix-summary")).toHaveTextContent(
      "AI summary (gemini), citing only the incidents below",
    );
    const fix = screen.getByTestId("past-fix");
    expect(fix).toHaveTextContent("71% similar");
    await userEvent.click(within(fix).getByRole("button", { name: "Use this fix…" }));
    const dialog = screen.getByRole("dialog", { name: "Resolve the incident" });
    const box = within(dialog).getByLabelText("What fixed it?");
    // Copied, not applied: the technician can still change it before saving.
    expect(box).toHaveValue("Rebooted access point AP-3 (as in INC-2026-0040)");
    await userEvent.clear(box);
    await userEvent.type(box, "Rebooted AP-3 again");
    await userEvent.click(within(dialog).getByRole("button", { name: "Mark as resolved" }));
    await waitFor(() => {
      expect(calls.find((c) => c.path.endsWith("/resolve"))?.body).toEqual({
        summary: "Rebooted AP-3 again",
      });
    });
  });

  it("works without an AI summary and is not asked for by the reporter", async () => {
    const { calls } = detail({
      user: me("employee", 1),
      routes: { "GET /incidents/INC-2026-0001": incident({ status: "IN_PROGRESS" }) },
    });
    expect(await screen.findByText("Wi-Fi down")).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/suggested-resolution"))).toBe(false);
  });
});
