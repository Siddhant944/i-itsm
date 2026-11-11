import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { syncServerTime } from "../lib/serverTime";
import { incident, renderPage } from "../test/utils";
import { PriorityBadge, RoleBadge, SLAStatusBadge, StatusBadge } from "./Badge";
import { Button } from "./Button";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { DataTable } from "./DataTable";
import { ChipGroup, TextField } from "./Field";
import { FilterBar } from "./FilterBar";
import { LoadBar } from "./LoadBar";
import { Modal } from "./Modal";
import { NotificationBell } from "./NotificationBell";
import { SLAChip } from "./SLAChip";
import { EmptyState, ErrorState, QueryView, Skeleton } from "./States";
import { ToastProvider, useToasts } from "./Toasts";

afterEach(() => {
  vi.useRealTimers();
});

describe("badges", () => {
  it("name the status, priority, SLA state and role in words", () => {
    render(
      <>
        <StatusBadge status="IN_PROGRESS" />
        <PriorityBadge priority="P1" />
        <PriorityBadge priority={null} />
        <SLAStatusBadge status="at_risk" />
        <RoleBadge role="team_lead" />
      </>,
    );
    for (const text of ["In progress", "P1 Critical", "Unprioritised", "At risk", "Team Lead"]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
  });

  it("shows an AI suggestion's confidence as a band and a number", () => {
    render(<ConfidenceBadge confidence={0.82} />);
    expect(screen.getByText("High confidence · 82%")).toBeInTheDocument();
  });
});

describe("SLAChip", () => {
  it("counts down on the application clock, at the application's speed", () => {
    vi.useFakeTimers();
    // The demo clock runs ×10: three real seconds are thirty SLA seconds.
    syncServerTime("2026-11-11T04:10:00+00:00", "10");
    const { sla } = incident();
    render(<SLAChip sla={sla} status="ASSIGNED" />);
    expect(screen.getByTestId("sla-chip")).toHaveTextContent("Response due in 5m 00s");
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByTestId("sla-chip")).toHaveTextContent("Response due in 4m 30s");
  });
});

describe("Button", () => {
  it("cannot be clicked twice while its action runs", async () => {
    const onClick = vi.fn();
    render(
      <Button busy onClick={onClick}>
        Save
      </Button>,
    );
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("DataTable", () => {
  it("renders a captioned table and opens a row on click", async () => {
    const open = vi.fn();
    render(
      <DataTable
        caption="People"
        rows={[{ id: 1, name: "Asha" }]}
        rowKey={(row) => row.id}
        onRowClick={open}
        columns={[{ key: "name", header: "Name", cell: (row) => row.name }]}
      />,
    );
    const table = screen.getByRole("table", { name: "People" });
    expect(within(table).getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    await userEvent.click(within(table).getByText("Asha"));
    expect(open).toHaveBeenCalledWith({ id: 1, name: "Asha" });
  });
});

describe("fields", () => {
  it("ties a label, a hint and an error to the input", () => {
    const { rerender } = render(<TextField label="Email" hint="Campus address" />);
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "false");
    expect(screen.getByText("Campus address")).toBeInTheDocument();
    rerender(<TextField label="Email" hint="Campus address" error="Already taken" />);
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Already taken");
    expect(screen.queryByText("Campus address")).not.toBeInTheDocument();
  });

  it("toggles chips on and off", async () => {
    function Harness() {
      const [selected, setSelected] = useState<string[]>(["a"]);
      return (
        <ChipGroup
          label="Letters"
          selected={selected}
          onChange={setSelected}
          options={[
            { value: "a", label: "A" },
            { value: "b", label: "B" },
          ]}
        />
      );
    }
    render(<Harness />);
    const a = screen.getByRole("button", { name: "A" });
    const b = screen.getByRole("button", { name: "B" });
    expect(a).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(b);
    await userEvent.click(a);
    expect(a).toHaveAttribute("aria-pressed", "false");
    expect(b).toHaveAttribute("aria-pressed", "true");
  });
});

describe("FilterBar", () => {
  it("applies on submit, resets, and says how many filters are active", async () => {
    const onApply = vi.fn();
    const onReset = vi.fn();
    render(
      <FilterBar activeCount={2} onApply={onApply} onReset={onReset}>
        <TextField label="Text" />
      </FilterBar>,
    );
    expect(screen.getByTestId("active-filters")).toHaveTextContent("2 filters applied");
    await userEvent.type(screen.getByLabelText("Text"), "wifi{Enter}");
    expect(onApply).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});

describe("loading, empty and error states", () => {
  const query = (over: object) => ({
    isPending: false,
    isError: false,
    error: null,
    data: undefined as string[] | undefined,
    refetch: vi.fn(),
    ...over,
  });
  const view = (q: ReturnType<typeof query>) => (
    <QueryView
      query={q}
      loadingLabel="Loading things"
      isEmpty={(rows) => rows.length === 0}
      empty={<EmptyState title="Nothing yet" hint="Add one" />}
    >
      {(rows) => <p>{rows.join(",")}</p>}
    </QueryView>
  );

  it("shows a labelled skeleton while loading", () => {
    render(view(query({ isPending: true })));
    expect(screen.getByRole("status", { name: "Loading things" })).toBeInTheDocument();
  });

  it("shows the API's message and a retry on failure", async () => {
    const failed = query({ isError: true, error: new ApiError(503, "The database is down.") });
    render(view(failed));
    expect(screen.getByRole("alert")).toHaveTextContent("The database is down.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(failed.refetch).toHaveBeenCalled();
  });

  it("shows the empty state, then the data", () => {
    const { rerender } = render(view(query({ data: [] })));
    expect(screen.getByText("Nothing yet")).toBeInTheDocument();
    rerender(view(query({ data: ["a", "b"] })));
    expect(screen.getByText("a,b")).toBeInTheDocument();
  });

  it("includes field problems in an error", () => {
    render(<ErrorState error={new ApiError(422, "Invalid.", "x", { name: "Taken." })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Invalid. Taken.");
    render(<Skeleton rows={2} />);
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
  });
});

describe("Modal", () => {
  it("is a labelled dialog that closes on Escape and on its close button", async () => {
    const onClose = vi.fn();
    render(
      <Modal title="Resolve" onClose={onClose}>
        <p>Body</p>
      </Modal>,
    );
    expect(screen.getByRole("dialog", { name: "Resolve" })).toHaveAttribute("aria-modal", "true");
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe("Toasts", () => {
  function Trigger() {
    const toasts = useToasts();
    return (
      <>
        <button
          onClick={() => {
            toasts.success("Saved");
          }}
        >
          ok
        </button>
        <button
          onClick={() => {
            toasts.error(new ApiError(409, "That transition is not allowed."));
          }}
        >
          fail
        </button>
      </>
    );
  }

  it("announces successes politely and errors as alerts, and can be dismissed", async () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByText("ok"));
    await userEvent.click(screen.getByText("fail"));
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    expect(screen.getByRole("alert")).toHaveTextContent("That transition is not allowed.");
    await userEvent.click(
      within(screen.getByRole("alert")).getByRole("button", { name: "Dismiss" }),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("disappears by itself", () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );
    act(() => {
      screen.getByText("ok").click();
    });
    expect(screen.getByRole("status")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(6000);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("LoadBar", () => {
  it("is a meter against the 10-point cap", () => {
    render(<LoadBar load={7} max={10} />);
    const meter = screen.getByRole("meter", { name: "Workload" });
    expect(meter).toHaveAttribute("aria-valuenow", "7");
    expect(meter).toHaveAttribute("aria-valuemax", "10");
    expect(screen.getByText("7 / 10")).toBeInTheDocument();
  });
});

describe("NotificationBell", () => {
  const item = {
    id: 7,
    subject: "INC-2026-0001 was assigned to you",
    body: "",
    channel: "in_app",
    event: "assigned",
    status: "sent",
    incident_id: "INC-2026-0001",
    created_at: "2026-11-11T04:00:00Z",
    read_at: null,
  };

  it("shows the unread count, lists the latest and marks one as read", async () => {
    const { calls } = renderPage(<NotificationBell incidentHref={(id) => `/x/${id}`} />, {
      routes: {
        "GET /notifications": { unread: 3, latest: [item] },
        "POST /notifications/7/read": { ...item, read_at: "2026-11-11T04:01:00Z" },
      },
    });
    expect(await screen.findByTestId("unread-count")).toHaveTextContent("3");
    await userEvent.click(screen.getByRole("button", { name: "Notifications, 3 unread" }));
    const panel = screen.getByRole("region", { name: "Notifications" });
    expect(within(panel).getByText(item.subject)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Open INC-2026-0001" })).toHaveAttribute(
      "href",
      "/x/INC-2026-0001",
    );
    await userEvent.click(within(panel).getByRole("button", { name: "Mark as read" }));
    expect(calls.some((c) => c.method === "POST" && c.path === "/notifications/7/read")).toBe(true);
  });

  it("says so when there is nothing", async () => {
    renderPage(<NotificationBell incidentHref={(id) => id} />);
    await userEvent.click(await screen.findByRole("button", { name: "Notifications, 0 unread" }));
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument();
    expect(screen.queryByTestId("unread-count")).not.toBeInTheDocument();
  });
});
