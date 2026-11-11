import { afterEach, describe, expect, it, vi } from "vitest";

import { toApiError } from "../api/client";
import type { IncidentSummary } from "../api/hooks";
import { EMPTY_DRAFT, countActive, toFilters } from "../pages/admin/searchFilters";
import { incident } from "../test/utils";
import { confidenceBand } from "./confidence";
import {
  formatDateTime,
  formatDuration,
  formatHours,
  formatMinutes,
  formatPercent,
  parseKeywords,
  titleCase,
} from "./format";
import { resetServerTime, serverNow, syncServerTime } from "./serverTime";
import { describeSla } from "./sla";
import { byUrgency } from "./sort";

afterEach(() => {
  vi.useRealTimers();
});

describe("format", () => {
  it("shows stored UTC times in IST", () => {
    expect(formatDateTime("2026-11-11T04:00:00Z")).toBe("11 Nov 2026, 09:30 IST");
    expect(formatDateTime(null)).toBe("—");
  });

  it("shows the two largest units of a duration", () => {
    expect(formatDuration(45_000)).toBe("45s");
    expect(formatDuration(252_000)).toBe("4m 12s");
    expect(formatDuration(7_500_000)).toBe("2h 05m");
    expect(formatDuration(100 * 3_600_000)).toBe("4d 4h");
    expect(formatDuration(-90_000)).toBe("1m 30s");
  });

  it("treats API shares as percentages already", () => {
    expect(formatPercent(23.7)).toBe("23.7%");
    expect(formatPercent(100)).toBe("100%");
    expect(formatPercent(null)).toBe("—");
  });

  it("formats hours, minutes, keywords and identifiers", () => {
    expect(formatHours(0.5)).toBe("30 min");
    expect(formatHours(46.12)).toBe("46.1 h");
    expect(formatHours(null)).toBe("—");
    expect(formatMinutes(30)).toBe("30 min");
    expect(formatMinutes(120)).toBe("2 h");
    expect(formatMinutes(90)).toBe("1.5 h");
    expect(parseKeywords(" wifi, Network ,, lan ")).toEqual(["wifi", "Network", "lan"]);
    expect(titleCase("load_based")).toBe("Load based");
  });
});

describe("confidence bands", () => {
  it("are coarse on purpose", () => {
    expect(confidenceBand(0.9).label).toBe("High confidence");
    expect(confidenceBand(0.75).label).toBe("High confidence");
    expect(confidenceBand(0.5).label).toBe("Medium confidence");
    expect(confidenceBand(0.2).label).toBe("Low confidence");
  });
});

describe("the application clock", () => {
  it("is the browser clock until the server has spoken", () => {
    resetServerTime();
    expect(Math.abs(serverNow() - Date.now())).toBeLessThan(50);
  });

  it("runs at the server's rate from the server's time", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    syncServerTime("2026-11-11T04:00:00+00:00", "10.0");
    vi.advanceTimersByTime(3000);
    expect(serverNow()).toBe(Date.parse("2026-11-11T04:00:30Z"));
  });

  it("stands still with a fake clock and ignores nonsense", () => {
    vi.useFakeTimers();
    syncServerTime("2026-11-11T04:00:00+00:00", "0.0");
    syncServerTime("not a date", "1");
    syncServerTime(null, null);
    vi.advanceTimersByTime(60_000);
    expect(serverNow()).toBe(Date.parse("2026-11-11T04:00:00Z"));
  });
});

describe("describeSla", () => {
  const now = Date.parse("2026-11-11T04:10:00Z");
  const base = incident();
  const sla = base.sla;
  if (sla === null) throw new Error("fixture has an SLA");

  it("counts down to the response deadline until someone acknowledges", () => {
    expect(describeSla(sla, "ASSIGNED", now)).toEqual({
      tone: "good",
      text: "Response due in 5m 00s",
    });
  });

  it("switches to the resolution deadline after the response", () => {
    const responded = { ...sla, responded_at: "2026-11-11T04:05:00Z" };
    expect(describeSla(responded, "IN_PROGRESS", now).text).toBe("Resolution due in 1h 50m");
  });

  it("takes its colour from the server's status", () => {
    expect(describeSla({ ...sla, response_status: "at_risk" }, "ASSIGNED", now).tone).toBe("warn");
  });

  it("BR-07 shows overdue once the deadline has passed or the server says breached", () => {
    const late = Date.parse("2026-11-11T04:16:00Z");
    expect(describeSla(sla, "ASSIGNED", late)).toEqual({
      tone: "bad",
      text: "Response overdue by 1m 00s",
    });
    expect(describeSla({ ...sla, response_status: "breached" }, "ASSIGNED", now).tone).toBe("bad");
  });

  it("says paused on hold, and met or breached once the fix is in", () => {
    expect(describeSla({ ...sla, paused: true }, "ON_HOLD", now).text).toBe("SLA paused");
    expect(describeSla(sla, "RESOLVED", now).text).toBe("SLA met");
    expect(describeSla({ ...sla, resolution_status: "breached" }, "CLOSED", now).text).toBe(
      "SLA breached",
    );
    expect(describeSla(null, "NEW", now).text).toBe("No SLA yet");
  });
});

describe("queue order", () => {
  const row = (id: string, priority: "P1" | "P3", status: "ASSIGNED" | "RESOLVED", at: string) =>
    ({ id, priority, status, created_at: at }) as IncidentSummary;

  it("puts open work first, then priority, then age", () => {
    const rows = [
      row("done-p1", "P1", "RESOLVED", "2026-11-01T00:00:00Z"),
      row("new-p3", "P3", "ASSIGNED", "2026-11-03T00:00:00Z"),
      row("old-p3", "P3", "ASSIGNED", "2026-11-02T00:00:00Z"),
      row("p1", "P1", "ASSIGNED", "2026-11-04T00:00:00Z"),
    ];
    expect(rows.sort(byUrgency).map((r) => r.id)).toEqual(["p1", "old-p3", "new-p3", "done-p1"]);
  });
});

describe("search filters", () => {
  it("sends nothing narrowing when the form is empty", () => {
    const filters = toFilters(EMPTY_DRAFT, 0);
    expect(filters).toMatchObject({ text: null, statuses: [], limit: 25, offset: 0 });
    expect(countActive(EMPTY_DRAFT)).toBe(0);
  });

  it("maps all nine filters and reads dates as IST days", () => {
    const draft = {
      ...EMPTY_DRAFT,
      text: " wifi ",
      incidentId: "INC-2026-0001",
      statuses: ["NEW" as const],
      priorities: ["P1" as const],
      slaStatuses: ["breached" as const],
      categoryId: "2",
      serviceId: "3",
      assigneeId: "4",
      reporterId: "5",
      from: "2026-11-01",
      to: "2026-11-02",
    };
    expect(toFilters(draft, 50)).toMatchObject({
      text: "wifi",
      incident_id: "INC-2026-0001",
      statuses: ["NEW"],
      priorities: ["P1"],
      sla_statuses: ["breached"],
      category_ids: [2],
      service_ids: [3],
      assignee_ids: [4],
      reporter_ids: [5],
      created_from: "2026-10-31T18:30:00.000Z",
      created_to: "2026-11-02T18:29:59.999Z",
      offset: 50,
    });
    expect(countActive(draft)).toBe(10);
  });
});

describe("API errors", () => {
  it("carry the server's sentence and its field errors", () => {
    const error = toApiError(422, {
      error: {
        code: "invalid_user_input",
        message: "Some fields are invalid.",
        details: { field_errors: { name: "Taken." } },
      },
    });
    expect(error.message).toBe("Some fields are invalid.");
    expect(error.fieldErrors).toEqual({ name: "Taken." });
    expect(toApiError(500, "<html>").message).toBe("The request failed (500).");
  });
});
