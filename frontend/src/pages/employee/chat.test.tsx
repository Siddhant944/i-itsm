import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";

import { incident, me, renderPage } from "../../test/utils";
import { ChatReportPage } from "./ChatReportPage";
import { rankServices } from "./chatHelpers";

beforeAll(() => {
  // The conversation scrolls itself; jsdom does not lay anything out.
  Element.prototype.scrollTo = () => {};
});

const REPORTED = {
  incident: incident({ id: "INC-2026-0042", status: "ASSIGNED", priority: "P2" }),
  suggestion: { category_id: 1, confidence: 0.82, source: "rules" },
  assignment: { technician_id: 3, score: 0.9, reasons: ["Has networking"] },
  needs_triage: false,
  queued_for_team_lead: false,
};

async function answer(text: string) {
  await userEvent.type(await screen.findByLabelText("Your answer"), text);
  await userEvent.click(screen.getByRole("button", { name: "Send" }));
}

async function choose(name: string | RegExp) {
  await userEvent.click(await screen.findByRole("button", { name }));
}

describe("chatbot-based reporting (P4.13)", () => {
  it("asks one question at a time and files the incident with the answers", async () => {
    const { calls } = renderPage(<ChatReportPage />, {
      user: me("employee"),
      routes: {
        "POST /incidents/classify": { category_id: 1, confidence: 0.82, source: "rules" },
        "POST /incidents": REPORTED,
      },
    });
    expect(await screen.findByText("In one line, what is wrong?")).toBeInTheDocument();
    await answer("Wifi keeps dropping");
    await answer("No signal in the library since this morning");
    await choose("Campus Wi-Fi");
    await choose("My team or department");
    await choose("It works, but badly");

    // The AI's category comes with its confidence and is applied only on a yes (§6.1).
    const log = screen.getByRole("log", { name: "Conversation" });
    expect(await within(log).findByText(/This looks like a/)).toHaveTextContent("Network");
    expect(within(log).getByText(/82%/)).toBeInTheDocument();
    await choose("Yes, Network");
    await choose("Report it");

    expect(await within(log).findByText(/Done: INC-2026-0042/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open INC-2026-0042" })).toBeInTheDocument();
    const sent = calls.find((c) => c.method === "POST" && c.path === "/incidents");
    expect(sent?.body).toEqual({
      title: "Wifi keeps dropping",
      description: "No signal in the library since this morning",
      service_id: 1,
      impact: 2,
      urgency: 2,
      category_id: 1,
      follow: null,
    });
  });

  it("offers a look-alike to follow instead, and leaves the category to the desk on a no", async () => {
    const { calls } = renderPage(<ChatReportPage />, {
      user: me("employee"),
      routes: {
        "POST /incidents/classify": { category_id: 1, confidence: 0.4, source: "rules" },
        "POST /incidents/similar": {
          provider: "tfidf",
          candidates: [
            {
              id: "INC-2026-0007",
              title: "Library wifi is down",
              status: "ASSIGNED",
              score: 0.81,
              reasons: ["text 70 % alike", "same service"],
            },
          ],
        },
        "POST /incidents": {
          ...REPORTED,
          followed: { id: "INC-2026-0007", title: "x", status: "ASSIGNED" },
        },
      },
    });
    await answer("Wifi down");
    await answer("The library wifi is not working");
    await choose("Campus Wi-Fi");
    expect(await screen.findByText(/This may already be reported/)).toHaveTextContent("81% match");
    await choose("Follow INC-2026-0007");
    await choose("Just me");
    await choose("I am blocked");
    await choose("Let the help desk decide");
    await choose("Report it");
    expect(await screen.findByText(/You are now following INC-2026-0007/)).toBeInTheDocument();
    const sent = calls.find((c) => c.method === "POST" && c.path === "/incidents");
    expect(sent?.body).toMatchObject({ follow: "INC-2026-0007", category_id: null, urgency: 3 });
  });

  it("puts the services the reporter named first", () => {
    const services = [
      { name: "Campus Email" },
      { name: "Exam Portal" },
      { name: "Fee Payment Portal" },
      { name: "VPN" },
    ];
    // Two words beat one: "payment portal" is the fee portal, not the exam portal.
    expect(rankServices(services, "the payment portal fails")[0]?.name).toBe("Fee Payment Portal");
    expect(rankServices(services, "my vpn drops")[0]?.name).toBe("VPN");
    expect(rankServices(services, "nothing in particular").map((s) => s.name)).toEqual([
      "Campus Email",
      "Exam Portal",
      "Fee Payment Portal",
      "VPN",
    ]);
  });
});
