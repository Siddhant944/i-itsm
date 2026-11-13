import { useDictation } from "../lib/speech";

/**
 * A microphone toggle that dictates into a field (P4.12). Renders nothing where the browser
 * has no speech recognition, so no one is offered a button that cannot work.
 */
export function DictateButton({
  onText,
  label = "Dictate",
}: {
  onText: (text: string) => void;
  label?: string;
}) {
  const dictation = useDictation(onText);
  if (!dictation.supported) return null;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        aria-pressed={dictation.listening}
        onClick={dictation.listening ? dictation.stop : dictation.start}
        className={`inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium focus-visible:outline-2 focus-visible:outline-accent ${
          dictation.listening
            ? "border-danger bg-danger text-white"
            : "border-line bg-surface text-ink hover:bg-raised"
        }`}
      >
        <span aria-hidden="true">{dictation.listening ? "■" : "🎤"}</span>
        {dictation.listening ? "Stop dictating" : label}
      </button>
      <p aria-live="polite" className="text-xs text-muted">
        {dictation.error ??
          (dictation.listening
            ? dictation.interim === ""
              ? "Listening… speak now."
              : `Heard: “${dictation.interim}”`
            : "Or say what happened; the words are added below what you typed.")}
      </p>
    </div>
  );
}
