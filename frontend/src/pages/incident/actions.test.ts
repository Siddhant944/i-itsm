import { describe, expect, it } from "vitest";

import { incident, me } from "../../test/utils";
import { availableActions, pendingQuestion, timelineOf } from "./actions";

const on = (flags: object) =>
  Object.entries(flags)
    .filter(([, value]) => value === true)
    .map(([key]) => key)
    .sort();

describe("availableActions", () => {
  it("offers the reporter only what a reporter may do", () => {
    const reporter = me("employee", 1);
    expect(on(availableActions(incident({ status: "ASSIGNED" }), reporter))).toEqual([
      "cancel",
      "provideInformation",
    ]);
    expect(on(availableActions(incident({ status: "RESOLVED" }), reporter))).toEqual(["verify"]);
    expect(on(availableActions(incident({ status: "CLOSED" }), reporter))).toEqual([]);
  });

  it("BR-01 offers another employee nothing", () => {
    expect(on(availableActions(incident(), me("employee", 2)))).toEqual([]);
  });

  it("walks the assignee through the lifecycle one legal step at a time", () => {
    const tech = me("technician", 3);
    const step = (status: Parameters<typeof incident>[0]) =>
      on(availableActions(incident(status), tech));
    expect(step({ status: "ASSIGNED" })).toContain("acknowledge");
    expect(step({ status: "ASSIGNED" })).not.toContain("resolve");
    expect(step({ status: "ACKNOWLEDGED" })).toContain("start");
    expect(step({ status: "IN_PROGRESS" })).toEqual(
      expect.arrayContaining(["resolve", "requestInformation", "note"]),
    );
    expect(step({ status: "ON_HOLD" })).toContain("resume");
    expect(step({ status: "ON_HOLD" })).not.toContain("resolve");
    expect(step({ status: "VERIFIED" })).toEqual(["close"]);
  });

  it("BR-02 keeps another technician's hands off, but lets a lead reassign", () => {
    const other = on(availableActions(incident(), me("technician", 9)));
    expect(other).not.toContain("acknowledge");
    const lead = on(availableActions(incident(), me("team_lead", 4), [3, 4]));
    expect(lead).toEqual(expect.arrayContaining(["reassign", "acknowledge", "overridePriority"]));
    expect(on(availableActions(incident(), me("technician", 3)))).not.toContain("reassign");
  });

  it("offers a lead nothing on another team's incident, as the API would refuse it", () => {
    // The lead reported it, so may see it, but its assignee (3) is not in the lead's team.
    const mine = incident({ reporter_id: 4 });
    expect(on(availableActions(mine, me("team_lead", 4), [4, 9]))).toEqual([
      "cancel",
      "provideInformation",
    ]);
  });

  it("lets a lead assign what is queued for a team lead (D-028)", () => {
    const queued = incident({ status: "CLASSIFIED", assignee_id: null });
    expect(on(availableActions(queued, me("team_lead", 4), [3, 4]))).toEqual(
      expect.arrayContaining(["reassign", "overridePriority"]),
    );
    expect(on(availableActions(queued, me("technician", 3)))).toEqual([]);
  });

  it("does not offer overrides on an incident the technician only reported", () => {
    const reportedByTech = incident({ reporter_id: 3, assignee_id: 9 });
    expect(on(availableActions(reportedByTech, me("technician", 3)))).toEqual([
      "cancel",
      "provideInformation",
    ]);
  });

  it("lets an administrator cancel anyone's open incident", () => {
    expect(on(availableActions(incident(), me("administrator", 8)))).toContain("cancel");
    expect(
      on(availableActions(incident({ status: "RESOLVED" }), me("administrator", 8))),
    ).not.toContain("cancel");
  });
});

describe("timeline", () => {
  it("tells the story in time order with questions and answers marked", () => {
    const story = timelineOf(
      incident({
        status: "CLOSED",
        acknowledged_at: "2026-11-11T04:05:00Z",
        notes: [
          {
            author_id: 3,
            created_at: "2026-11-11T04:20:00Z",
            kind: "info_request",
            text: "Where?",
          },
          {
            author_id: 1,
            created_at: "2026-11-11T04:30:00Z",
            kind: "info_response",
            text: "Library",
          },
          { author_id: 3, created_at: "2026-11-11T04:10:00Z", kind: "note", text: "Looking" },
        ],
        resolution: { resolver_id: 3, resolved_at: "2026-11-11T05:00:00Z", summary: "Rebooted AP" },
        feedback: { rating: 5, comment: "", given_at: "2026-11-11T05:10:00Z" },
        closed_at: "2026-11-11T05:10:00Z",
      }),
    );
    expect(story.map((entry) => entry.title)).toEqual([
      "Reported",
      "Acknowledged",
      "Work note",
      "Information requested",
      "Information provided",
      "Resolved",
      "Fix verified · rated 5/5",
      "Closed",
    ]);
    expect(story[3]?.kind).toBe("question");
  });

  it("finds the question the reporter still has to answer", () => {
    const asked = incident({
      status: "ON_HOLD",
      notes: [
        { author_id: 3, created_at: "2026-11-11T04:20:00Z", kind: "info_request", text: "Where?" },
      ],
    });
    expect(pendingQuestion(asked)).toBe("Where?");
    expect(pendingQuestion(incident({ ...asked, status: "IN_PROGRESS" }))).toBeNull();
    expect(pendingQuestion(incident({ status: "ON_HOLD" }))).toBeNull();
  });
});
