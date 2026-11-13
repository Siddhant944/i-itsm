import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Voice input for the report form (P4.12; the brief's "voice-based incident reporting").
 *
 * The browser's own Web Speech API turns speech into text on the device's speech service;
 * nothing is sent to our API until the reporter submits the form. Browsers without it
 * (Firefox, most of Safari) get no microphone button at all rather than a broken one.
 */

/** The parts of the (still vendor-prefixed) SpeechRecognition API we use. */
export interface RecognitionAlternative {
  transcript: string;
}
export interface RecognitionResult {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: RecognitionAlternative;
}
export interface RecognitionEvent {
  readonly resultIndex: number;
  readonly results: { readonly length: number; [index: number]: RecognitionResult };
}
export interface RecognitionErrorEvent {
  readonly error: string;
}
export interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: RecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}
type RecognitionConstructor = new () => Recognition;

/** The browser's SpeechRecognition class, or undefined where there is none. */
export function recognitionClass(): RecognitionConstructor | undefined {
  if (typeof window === "undefined") return undefined;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
}

const ERRORS: Record<string, string> = {
  "not-allowed": "Microphone access is blocked. Allow it in the browser to dictate.",
  "service-not-allowed": "Microphone access is blocked. Allow it in the browser to dictate.",
  "no-speech": "Nothing was heard. Try again, a little closer to the microphone.",
  "audio-capture": "No microphone was found.",
  network: "Speech recognition needs an internet connection.",
};

export interface Dictation {
  /** False where the browser has no speech recognition: render nothing. */
  supported: boolean;
  listening: boolean;
  /** Words heard so far that are not final yet, shown as a live preview. */
  interim: string;
  error: string | null;
  start: () => void;
  stop: () => void;
}

/**
 * Dictate into a field. Each final phrase is passed to ``onFinal``; the caller decides how
 * it joins the text already typed (the report form appends it).
 */
export function useDictation(onFinal: (text: string) => void, lang = "en-IN"): Dictation {
  const Ctor = recognitionClass();
  const recognition = useRef<Recognition | null>(null);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const deliver = useRef(onFinal);
  useEffect(() => {
    deliver.current = onFinal;
  }, [onFinal]);

  const stop = useCallback(() => {
    recognition.current?.stop();
  }, []);

  const start = useCallback(() => {
    if (Ctor === undefined || recognition.current !== null) return;
    const r = new Ctor();
    r.lang = lang;
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (event) => {
      let pending = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const best = result?.[0];
        if (result === undefined || best === undefined) continue;
        const text = best.transcript.trim();
        if (result.isFinal) {
          if (text !== "") deliver.current(text);
        } else {
          pending += `${text} `;
        }
      }
      setInterim(pending.trim());
    };
    r.onerror = (event) => {
      if (event.error !== "aborted") {
        setError(ERRORS[event.error] ?? "Dictation stopped unexpectedly. Try again.");
      }
    };
    r.onend = () => {
      recognition.current = null;
      setListening(false);
      setInterim("");
    };
    recognition.current = r;
    setError(null);
    setListening(true);
    r.start();
  }, [Ctor, lang]);

  // Leaving the page stops the microphone.
  useEffect(() => () => recognition.current?.stop(), []);

  return { supported: Ctor !== undefined, listening, interim, error, start, stop };
}

/** Add a dictated phrase to what is already typed, as a sentence of its own. */
export function appendSentence(existing: string, phrase: string): string {
  const sentence = phrase.charAt(0).toUpperCase() + phrase.slice(1);
  const ended = /[.!?]$/.test(sentence) ? sentence : `${sentence}.`;
  const base = existing.trimEnd();
  if (base === "") return ended;
  return /[.!?]$/.test(base) ? `${base} ${ended}` : `${base}. ${ended}`;
}
