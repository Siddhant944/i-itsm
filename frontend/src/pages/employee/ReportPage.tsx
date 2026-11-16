import { useEffect, useState, type SyntheticEvent } from "react";
import { Link, useNavigate } from "react-router";

import { ApiError, type Schemas } from "../../api/client";
import {
  useCategories,
  useClassify,
  useReportIncident,
  useServices,
  useSimilar,
} from "../../api/hooks";
import { Button } from "../../components/Button";
import { ConfidenceBadge } from "../../components/ConfidenceBadge";
import { DictateButton } from "../../components/DictateButton";
import { StatusBadge } from "../../components/Badge";
import { SelectField, TextArea, TextField } from "../../components/Field";
import { Card, ErrorState, PageHeader, Skeleton } from "../../components/States";
import { useToasts } from "../../components/Toasts";
import { confidenceBand } from "../../lib/confidence";
import { appendSentence } from "../../lib/speech";
import { usePortal } from "../../lib/usePortal";
import { incidentPath } from "../../shell/nav";

/** Blueprint §5.1: priority comes from plain-language answers, so it cannot be inflated. */
const IMPACT = [
  { value: 1, label: "Just me" },
  { value: 2, label: "My team or department" },
  { value: 3, label: "Many people or everyone" },
] as const;
const URGENCY = [
  { value: 1, label: "I have a workaround" },
  { value: 2, label: "It works, but badly" },
  { value: 3, label: "I am blocked" },
] as const;

const SUGGEST_AFTER_CHARS = 12;
const SUGGEST_DELAY_MS = 600;

type Similar = Schemas["SimilarIncidentResponse"];

/**
 * §6.2: open incidents that look like this report. The reporter may follow one instead of
 * filing the same problem twice; nothing is linked unless they choose to.
 */
function SimilarHint({
  candidates,
  following,
  onFollow,
}: {
  candidates: readonly Similar[];
  following: string | null;
  onFollow: (id: string | null) => void;
}) {
  return (
    <div
      data-testid="similar-incidents"
      role="status"
      className="rounded-lg border border-warn-line bg-warn-soft px-4 py-3 text-sm"
    >
      <p className="font-medium">This may already be reported</p>
      <p className="mt-1 text-xs text-muted">
        Follow an existing incident instead and you will be told when it is fixed. Or carry on if
        yours is a different problem.
      </p>
      <ul className="mt-2 space-y-2">
        {candidates.map((candidate) => (
          <li
            key={candidate.id}
            className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface px-3 py-2"
          >
            <span className="font-mono text-xs text-muted">{candidate.id}</span>
            <span className="font-medium">{candidate.title}</span>
            <StatusBadge status={candidate.status} />
            <span className="text-xs text-muted">
              {String(Math.round(candidate.score * 100))}% match · {candidate.reasons.join(" · ")}
            </span>
            {following === candidate.id ? (
              <Button
                small
                className="ml-auto"
                onClick={() => {
                  onFollow(null);
                }}
              >
                Following — undo
              </Button>
            ) : (
              <Button
                small
                className="ml-auto"
                onClick={() => {
                  onFollow(candidate.id);
                }}
              >
                Follow this instead
              </Button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Choice({
  legend,
  name,
  options,
  value,
  onChange,
}: {
  legend: string;
  name: string;
  options: readonly { value: number; label: string }[];
  value: number | null;
  onChange: (value: number) => void;
}) {
  return (
    <fieldset>
      <legend className="mb-1 text-sm font-medium text-ink">{legend}</legend>
      <div className="grid gap-2 sm:grid-cols-3">
        {options.map((option) => (
          <label
            key={option.value}
            className={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm ${value === option.value ? "border-accent bg-accent-soft" : "border-line bg-surface hover:bg-raised"}`}
          >
            <input
              type="radio"
              name={name}
              checked={value === option.value}
              onChange={() => {
                onChange(option.value);
              }}
            />
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** The intake form (FR: report an incident). The AI's category is a suggestion, never silent. */
export function ReportPage() {
  const portal = usePortal();
  const navigate = useNavigate();
  const toasts = useToasts();
  const services = useServices();
  const categories = useCategories();
  const classify = useClassify();
  const report = useReportIncident();
  const similar = useSimilar();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [impact, setImpact] = useState<number | null>(null);
  const [urgency, setUrgency] = useState<number | null>(null);
  const [follow, setFollow] = useState<string | null>(null);
  // Like the suggestion, the similar incidents belong to the exact text and service they
  // were found for.
  const [lookalikes, setLookalikes] = useState<{ key: string; found: Similar[] } | null>(null);
  // A suggestion belongs to the text it was computed for; it is never shown for any other.
  const [suggestion, setSuggestion] = useState<{
    text: string;
    found: Schemas["SuggestionResponse"] | null;
  } | null>(null);

  const text = `${title} ${description}`.trim();
  const { mutate: requestSuggestion } = classify;
  useEffect(() => {
    if (text.length < SUGGEST_AFTER_CHARS) return;
    const timer = window.setTimeout(() => {
      requestSuggestion(text, {
        onSuccess: (found) => {
          setSuggestion({ text, found });
        },
        onError: () => {
          setSuggestion(null);
        },
      });
    }, SUGGEST_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [text, requestSuggestion]);

  const similarKey = `${title.trim()}\n${description.trim()}\n${serviceId}`;
  const { mutate: findSimilar } = similar;
  useEffect(() => {
    if (title.trim().length < SUGGEST_AFTER_CHARS) return;
    const timer = window.setTimeout(() => {
      findSimilar(
        {
          title: title.trim(),
          description: description.trim(),
          service_id: serviceId === "" ? null : Number(serviceId),
        },
        {
          onSuccess: (found) => {
            setLookalikes({ key: similarKey, found: found.candidates });
          },
          onError: () => {
            setLookalikes(null);
          },
        },
      );
    }, SUGGEST_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [similarKey, title, description, serviceId, findSimilar]);

  if (services.isPending || categories.isPending) return <Skeleton label="Loading the form" />;
  if (services.isError || categories.isError) {
    return (
      <ErrorState
        error={services.error ?? categories.error}
        onRetry={() => {
          void services.refetch();
          void categories.refetch();
        }}
      />
    );
  }

  const shown = suggestion !== null && suggestion.text === text ? suggestion.found : null;
  const suggested =
    shown?.category_id === null || shown === null
      ? undefined
      : categories.data.find((category) => category.id === shown.category_id);
  const fieldErrors = report.error instanceof ApiError ? report.error.fieldErrors : {};
  const candidates = lookalikes !== null && lookalikes.key === similarKey ? lookalikes.found : [];
  // A followed incident that is no longer among the matches is not followed any more.
  const following = candidates.some((c) => c.id === follow) ? follow : null;
  // BR-09: the same person's near-identical report within 30 minutes is refused with 409.
  const repeatOf =
    report.error instanceof ApiError && report.error.code === "duplicate_incident"
      ? (report.error.details.existing_incident_id ?? null)
      : null;
  const ready =
    title.trim() !== "" &&
    description.trim() !== "" &&
    serviceId !== "" &&
    impact !== null &&
    urgency !== null;

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    if (!ready) return;
    report.mutate(
      {
        title: title.trim(),
        description: description.trim(),
        service_id: Number(serviceId),
        impact,
        urgency,
        category_id: categoryId === "" ? null : Number(categoryId),
        follow: following,
      },
      {
        onSuccess: (reported) => {
          const { incident } = reported;
          const followed = reported.followed ?? null;
          if (followed !== null) {
            toasts.success(`You are following ${followed.id}. We will tell you when it is fixed.`);
            void navigate(incidentPath(portal, incident.id));
            return;
          }
          const outcome = reported.queued_for_team_lead
            ? "queued for a team lead"
            : reported.needs_triage
              ? "waiting for triage"
              : "assigned to a technician";
          toasts.success(
            `${incident.id} reported${incident.priority === null ? "" : ` as ${incident.priority}`} and ${outcome}.`,
          );
          // Left blank, the category was chosen by the classifier: say so, with how sure it
          // was, rather than let it appear on the incident unannounced.
          const applied = reported.suggestion;
          const category = categories.data.find((c) => c.id === applied?.category_id);
          if (applied !== null && category !== undefined) {
            toasts.info(
              `Classified automatically as ${category.name} (${confidenceBand(applied.confidence).label.toLowerCase()}, ${String(Math.round(applied.confidence * 100))}%). The help desk can change it.`,
            );
          }
          void navigate(incidentPath(portal, incident.id));
        },
      },
    );
  };

  return (
    <>
      <PageHeader
        title="Report an incident"
        subtitle="Tell us what is wrong in your own words. We work out the priority from your answers."
      />
      <form onSubmit={submit} className="space-y-5" noValidate>
        <Card>
          <div className="space-y-4">
            <TextField
              label="What is the problem, in one line?"
              maxLength={200}
              required
              value={title}
              error={fieldErrors.title}
              onChange={(event) => {
                setTitle(event.target.value);
              }}
            />
            <TextArea
              label="What happened?"
              hint="What you were doing, what you saw, and where you are."
              maxLength={5000}
              required
              value={description}
              error={fieldErrors.description}
              onChange={(event) => {
                setDescription(event.target.value);
              }}
            />
            <DictateButton
              label="Describe it by voice"
              onText={(text) => {
                setDescription((current) => appendSentence(current, text));
              }}
            />
            <SelectField
              label="Which service is affected?"
              required
              value={serviceId}
              error={fieldErrors.service_id}
              onChange={(event) => {
                setServiceId(event.target.value);
              }}
            >
              <option value="">Choose a service…</option>
              {services.data.map((service) => (
                <option key={service.id} value={service.id}>
                  {service.name}
                </option>
              ))}
            </SelectField>
          </div>
        </Card>

        <Card>
          <div className="space-y-4">
            <Choice
              legend="Who is affected?"
              name="impact"
              options={IMPACT}
              value={impact}
              onChange={setImpact}
            />
            <Choice
              legend="Can you keep working?"
              name="urgency"
              options={URGENCY}
              value={urgency}
              onChange={setUrgency}
            />
          </div>
        </Card>

        <Card title="Category">
          <div className="space-y-3">
            {suggested !== undefined && shown !== null && (
              <div
                data-testid="ai-suggestion"
                className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-raised px-3 py-2 text-sm"
              >
                <span>
                  Suggested category: <strong>{suggested.name}</strong>
                </span>
                <ConfidenceBadge confidence={shown.confidence} />
                <span className="text-xs text-muted">
                  from {shown.source === "rules" ? "keyword rules" : shown.source}
                </span>
                {categoryId === String(suggested.id) ? (
                  <span className="ml-auto text-xs font-medium text-accent-strong">Applied</span>
                ) : (
                  <Button
                    small
                    className="ml-auto"
                    onClick={() => {
                      setCategoryId(String(suggested.id));
                    }}
                  >
                    Use this suggestion
                  </Button>
                )}
              </div>
            )}
            <SelectField
              label="Category"
              hint="Optional. Left blank, the incident is classified automatically from your description; you are told the result and the help desk can correct it."
              value={categoryId}
              error={fieldErrors.category_id}
              onChange={(event) => {
                setCategoryId(event.target.value);
              }}
            >
              <option value="">Let the help desk decide</option>
              {categories.data.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </SelectField>
          </div>
        </Card>

        {candidates.length > 0 && (
          <SimilarHint candidates={candidates} following={following} onFollow={setFollow} />
        )}

        {repeatOf !== null ? (
          <div
            role="alert"
            data-testid="repeat-report"
            className="rounded-lg border border-bad-line bg-bad-soft px-4 py-3 text-sm"
          >
            <p className="font-medium">You reported this a few minutes ago.</p>
            <p className="mt-1">
              It is{" "}
              <Link className="underline" to={incidentPath(portal, repeatOf)}>
                {repeatOf}
              </Link>
              . Add anything new there instead of reporting it again.
            </p>
          </div>
        ) : (
          report.isError && <ErrorState error={report.error} />
        )}
        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" busy={report.isPending} disabled={!ready}>
            {following === null ? "Submit incident" : `Follow ${following}`}
          </Button>
          {!ready && (
            <span className="text-xs text-muted">Answer every question above to submit.</span>
          )}
        </div>
      </form>
    </>
  );
}
