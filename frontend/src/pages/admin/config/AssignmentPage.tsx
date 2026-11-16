import { useState } from "react";

import type { Schemas } from "../../../api/client";
import { useAssignmentSettings, useSaveAssignmentSettings } from "../../../api/hooks";
import { Button } from "../../../components/Button";
import { Card, ErrorState, PageHeader, QueryView } from "../../../components/States";
import { useToasts } from "../../../components/Toasts";

type Settings = Schemas["AssignmentSettingsResponse"];
type Weights = Schemas["AssignmentWeights"];

const STRATEGY: Record<string, { label: string; blurb: string }> = {
  smart: {
    label: "Smart",
    blurb:
      "A weighted score of skill match, spare capacity, experience and past fixes on the service.",
  },
  skill_based: {
    label: "Skill based",
    blurb: "The best skill match wins; ties go to whoever carries less.",
  },
  load_based: {
    label: "Load based",
    blurb: "Whoever carries the least weighted load wins, regardless of skills.",
  },
};

const WEIGHTS: { key: keyof Weights; label: string }[] = [
  { key: "skills", label: "Skill coverage" },
  { key: "capacity", label: "Spare capacity" },
  { key: "experience", label: "Experience" },
  { key: "history", label: "Past fixes on the service" },
];

/** Whole percentages keep the sum exact; the API takes fractions. */
function toPercent(weights: Weights): Record<keyof Weights, number> {
  return {
    skills: Math.round(weights.skills * 100),
    capacity: Math.round(weights.capacity * 100),
    experience: Math.round(weights.experience * 100),
    history: Math.round(weights.history * 100),
  };
}

function Editor({ settings }: { settings: Settings }) {
  const save = useSaveAssignmentSettings();
  const toasts = useToasts();
  const [strategy, setStrategy] = useState(settings.strategy);
  const [percent, setPercent] = useState(() => toPercent(settings.weights));
  const total = WEIGHTS.reduce((sum, weight) => sum + percent[weight.key], 0);
  const smart = strategy === "smart";
  const valid = !smart || total === 100;

  return (
    <div className="space-y-5">
      <Card title="Strategy">
        <fieldset className="space-y-2">
          <legend className="sr-only">Assignment strategy</legend>
          {settings.available.map((name) => (
            <label
              key={name}
              className={`flex cursor-pointer gap-3 rounded-md border px-3 py-2 ${strategy === name ? "border-accent bg-accent-soft" : "border-line hover:bg-raised"}`}
            >
              <input
                type="radio"
                name="strategy"
                className="mt-1"
                checked={strategy === name}
                onChange={() => {
                  setStrategy(name);
                }}
              />
              <span>
                <span className="block text-sm font-medium">{STRATEGY[name]?.label ?? name}</span>
                <span className="block text-xs text-muted">{STRATEGY[name]?.blurb ?? ""}</span>
              </span>
            </label>
          ))}
        </fieldset>
      </Card>

      <Card title="Smart strategy weights">
        <div className="space-y-3">
          {WEIGHTS.map((weight) => (
            <div key={weight.key} className="flex items-center gap-3">
              <label htmlFor={`weight-${weight.key}`} className="w-52 text-sm">
                {weight.label}
              </label>
              <input
                id={`weight-${weight.key}`}
                type="range"
                min={0}
                max={100}
                step={5}
                disabled={!smart}
                value={percent[weight.key]}
                onChange={(event) => {
                  setPercent((current) => ({
                    ...current,
                    [weight.key]: Number(event.target.value),
                  }));
                }}
                className="flex-1 accent-(--accent)"
              />
              <span className="w-12 text-right text-sm tabular-nums">
                {String(percent[weight.key])}%
              </span>
            </div>
          ))}
          <p
            data-testid="weights-total"
            className={`text-sm font-medium ${total === 100 ? "text-good" : "text-bad"}`}
          >
            Total {String(total)}%{total === 100 ? "" : " — the weights must add up to 100%."}
          </p>
          {!smart && (
            <p className="text-xs text-muted">Weights only apply to the Smart strategy.</p>
          )}
        </div>
      </Card>

      {save.isError && <ErrorState error={save.error} />}
      <Button
        variant="primary"
        busy={save.isPending}
        disabled={!valid}
        onClick={() => {
          const weights = smart
            ? {
                skills: percent.skills / 100,
                capacity: percent.capacity / 100,
                experience: percent.experience / 100,
                history: percent.history / 100,
              }
            : settings.weights;
          save.mutate(
            { strategy, weights },
            {
              onSuccess: (saved) => {
                toasts.success(
                  `${STRATEGY[saved.strategy]?.label ?? saved.strategy} strategy is active for the next assignment.`,
                );
              },
            },
          );
        }}
      >
        Save assignment settings
      </Button>
    </div>
  );
}

/** Switch the assignment strategy at runtime and tune the smart weights (blueprint §5.3). */
export function AssignmentPage() {
  const settings = useAssignmentSettings();
  return (
    <>
      <PageHeader
        title="Assignment"
        subtitle="How new incidents are matched to technicians. Changes apply to the next assignment."
      />
      <QueryView query={settings} loadingLabel="Loading assignment settings">
        {(data) => <Editor key={JSON.stringify(data)} settings={data} />}
      </QueryView>
    </>
  );
}
