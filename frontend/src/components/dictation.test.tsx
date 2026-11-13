import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import {
  appendSentence,
  type Recognition,
  type RecognitionErrorEvent,
  type RecognitionEvent,
} from "../lib/speech";
import { DictateButton } from "./DictateButton";

/** A stand-in for the browser's SpeechRecognition that the test drives by hand. */
class FakeRecognition implements Recognition {
  static last: FakeRecognition | null = null;
  lang = "";
  continuous = false;
  interimResults = false;
  started = false;
  onresult: ((event: RecognitionEvent) => void) | null = null;
  onerror: ((event: RecognitionErrorEvent) => void) | null = null;
  onend: (() => void) | null = null;
  constructor() {
    FakeRecognition.last = this;
  }
  start() {
    this.started = true;
  }
  stop() {
    this.onend?.();
  }
  hear(transcript: string, isFinal: boolean) {
    const result = Object.assign([{ transcript }], { isFinal });
    this.onresult?.({ resultIndex: 0, results: [result] });
  }
}

type SpeechWindow = { webkitSpeechRecognition?: unknown; SpeechRecognition?: unknown };

function Form() {
  const [text, setText] = useState("The printer jams");
  return (
    <>
      <DictateButton
        onText={(phrase) => {
          setText((current) => appendSentence(current, phrase));
        }}
      />
      <output data-testid="text">{text}</output>
    </>
  );
}

afterEach(() => {
  delete (window as SpeechWindow).webkitSpeechRecognition;
  delete (window as SpeechWindow).SpeechRecognition;
  FakeRecognition.last = null;
});

describe("voice input (P4.12)", () => {
  it("offers no microphone where the browser cannot recognise speech", () => {
    render(<Form />);
    expect(screen.queryByRole("button", { name: /dictate/i })).not.toBeInTheDocument();
  });

  it("previews what it hears and adds each final phrase as a sentence", async () => {
    (window as SpeechWindow).webkitSpeechRecognition = FakeRecognition;
    render(<Form />);
    await userEvent.click(screen.getByRole("button", { name: "Dictate" }));
    const recognition = FakeRecognition.last;
    if (recognition === null) throw new Error("recognition was not created");
    expect(recognition.started).toBe(true);
    expect(recognition.lang).toBe("en-IN");
    expect(screen.getByRole("button", { name: "Stop dictating" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    act(() => {
      recognition.hear("on the second floor", false);
    });
    expect(screen.getByText(/Heard: “on the second floor”/)).toBeInTheDocument();
    expect(screen.getByTestId("text")).toHaveTextContent("The printer jams");

    act(() => {
      recognition.hear("on the second floor", true);
    });
    expect(screen.getByTestId("text")).toHaveTextContent("The printer jams. On the second floor.");

    await userEvent.click(screen.getByRole("button", { name: "Stop dictating" }));
    expect(screen.getByRole("button", { name: "Dictate" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("explains a blocked microphone in plain words", async () => {
    (window as SpeechWindow).SpeechRecognition = FakeRecognition;
    render(<Form />);
    await userEvent.click(screen.getByRole("button", { name: "Dictate" }));
    act(() => {
      FakeRecognition.last?.onerror?.({ error: "not-allowed" });
      FakeRecognition.last?.onend?.();
    });
    expect(screen.getByText(/Microphone access is blocked/)).toBeInTheDocument();
  });

  it("joins dictated phrases to typed text as sentences", () => {
    expect(appendSentence("", "wifi is down")).toBe("Wifi is down.");
    expect(appendSentence("It broke.", "again today")).toBe("It broke. Again today.");
    expect(appendSentence("It broke", "is it fixed?")).toBe("It broke. Is it fixed?");
  });
});
