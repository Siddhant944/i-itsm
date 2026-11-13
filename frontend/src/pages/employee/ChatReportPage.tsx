import { useEffect, useRef, useState, type ReactNode, type SyntheticEvent } from "react";
import { Link } from "react-router";

import { ApiError, type Schemas } from "../../api/client";
import {
  useCategories,
  useClassify,
  useReportIncident,
  useServices,
  useSimilar,
} from "../../api/hooks";
import { useAuth } from "../../auth/AuthContext";
import { Button } from "../../components/Button";
import { ConfidenceBadge } from "../../components/ConfidenceBadge";
import { DictateButton } from "../../components/DictateButton";
import { Card, ErrorState, PageHeader, Skeleton } from "../../components/States";
import { appendSentence } from "../../lib/speech";
import { usePortal } from "../../lib/usePortal";
import { incidentPath } from "../../shell/nav";
import { rankServices } from "./chatHelpers";

/**
 * P4.13: chatbot-based incident reporting (the brief's Innovation Challenge). A conversation
 * asks one plain question at a time and files the incident through the same API as the form,
 * so the same rules apply: priority from the two plain-language answers (§5.1), the AI's
 * category shown with its confidence and applied only if the reporter agrees (§6.1), and open
 * look-alikes offered to follow instead (§6.2). Speaking an answer works too (P4.12).
 */

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

type Step =
  | "title"
  | "details"
  | "service"
  | "duplicate"
  | "impact"
  | "urgency"
  | "category"
  | "confirm"
  | "sending"
  | "done";

interface Message {
  from: "bot" | "you";
  body: ReactNode;
}

interface Draft {
  title: string;
  description: string;
  service: Schemas["ServiceResponse"] | null;
  follow: Schemas["SimilarIncidentResponse"] | null;
  impact: number | null;
  urgency: number | null;
  categoryId: number | null;
}

const EMPTY: Draft = {
  title: "",
  description: "",
  service: null,
  follow: null,
  impact: null,
  urgency: null,
  categoryId: null,
};

export function ChatReportPage() {
  const { user } = useAuth();
  const portal = usePortal();
  const services = useServices();
  const categories = useCategories();
  const classify = useClassify();
  const similar = useSimilar();
  const reportIncident = useReportIncident();

  const greeting = (): Message[] => [
    {
      from: "bot",
      body: `Hello${user ? ` ${user.full_name.split(" ")[0] ?? ""}` : ""}. I'll ask a few short questions and report the problem for you.`,
    },
    { from: "bot", body: "In one line, what is wrong?" },
  ];
  const [messages, setMessages] = useState<Message[]>(greeting);
  const [step, setStep] = useState<Step>("title");
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [text, setText] = useState("");
  const [reported, setReported] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<Schemas["SuggestionResponse"] | null>(null);
  // The category suggestion is asked for as soon as the problem is described and awaited only
  // when it is needed, after the service and the two plain-language answers.
  const [pendingSuggestion, setPendingSuggestion] = useState<Promise<
    Schemas["SuggestionResponse"] | null
  > | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight });
    if (step === "title" || step === "details") input.current?.focus();
  }, [messages, step]);

  if (services.isPending || categories.isPending) return <Skeleton label="Loading the chat" />;
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
  const activeServices = services.data.filter((s) => s.active);
  const categoryName = (id: number | null) =>
    categories.data.find((c) => c.id === id)?.name ?? "Unknown";

  const say = (...added: Message[]) => {
    setMessages((current) => [...current, ...added]);
  };

  const askImpact = () => {
    say({ from: "bot", body: "Who is affected?" });
    setStep("impact");
  };

  const askCategory = (next: Draft, found: Schemas["SuggestionResponse"] | null) => {
    setSuggestion(found);
    if (found?.category_id == null) {
      say({
        from: "bot",
        body: "I couldn't tell what kind of problem this is, so the help desk will classify it.",
      });
      confirm(next);
      return;
    }
    say({
      from: "bot",
      body: (
        <span>
          This looks like a <strong>{categoryName(found.category_id)}</strong> problem{" "}
          <ConfidenceBadge confidence={found.confidence} />{" "}
          <span className="text-xs opacity-75">
            (from {found.source === "rules" ? "keyword rules" : "Gemini"})
          </span>
          . Shall I use that category?
        </span>
      ),
    });
    setStep("category");
  };

  const confirm = (final: Draft) => {
    setDraft(final);
    say({
      from: "bot",
      body: (
        <div className="space-y-1">
          <p>Here is what I'll report:</p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-sm">
            <dt className="font-medium">Problem</dt>
            <dd>{final.title}</dd>
            <dt className="font-medium">Service</dt>
            <dd>{final.service?.name}</dd>
            <dt className="font-medium">Affected</dt>
            <dd>{IMPACT.find((o) => o.value === final.impact)?.label}</dd>
            <dt className="font-medium">Can you work?</dt>
            <dd>{URGENCY.find((o) => o.value === final.urgency)?.label}</dd>
            <dt className="font-medium">Category</dt>
            <dd>
              {final.categoryId === null ? "Help desk decides" : categoryName(final.categoryId)}
            </dd>
            {final.follow !== null && (
              <>
                <dt className="font-medium">Instead</dt>
                <dd>you will follow {final.follow.id}</dd>
              </>
            )}
          </dl>
        </div>
      ),
    });
    setStep("confirm");
  };

  const submitText = (event: SyntheticEvent) => {
    event.preventDefault();
    const answer = text.trim();
    if (answer === "") return;
    setText("");
    say({ from: "you", body: answer });
    if (step === "title") {
      setDraft({ ...draft, title: answer.slice(0, 200) });
      say({
        from: "bot",
        body: "Tell me a bit more: what you were doing, what you saw, and where you are.",
      });
      setStep("details");
      return;
    }
    const next = { ...draft, description: answer.slice(0, 5000) };
    setDraft(next);
    setPendingSuggestion(
      classify.mutateAsync(`${next.title}\n${next.description}`).catch(() => null), // advice only
    );
    say({ from: "bot", body: "Which service is affected?" });
    setStep("service");
  };

  const chooseService = (service: Schemas["ServiceResponse"]) => {
    say({ from: "you", body: service.name });
    const next = { ...draft, service };
    setDraft(next);
    similar.mutate(
      { title: next.title, description: next.description, service_id: service.id },
      {
        onSuccess: (check) => {
          const best = check.candidates[0];
          if (best === undefined) {
            askImpact();
            return;
          }
          say({
            from: "bot",
            body: (
              <span>
                This may already be reported: <span className="font-mono text-xs">{best.id}</span>{" "}
                <strong>{best.title}</strong> ({String(Math.round(best.score * 100))}% match ·{" "}
                {best.reasons.join(" · ")}). Would you like to follow it instead? You'll be told
                when it's fixed.
              </span>
            ),
          });
          setStep("duplicate");
        },
        onError: askImpact, // advice only: a failed check never blocks a report
      },
    );
  };

  const chooseFollow = (follow: boolean) => {
    const best = similar.data?.candidates[0] ?? null;
    say({ from: "you", body: follow && best ? `Follow ${best.id}` : "No, mine is different" });
    setDraft({ ...draft, follow: follow ? best : null });
    askImpact();
  };

  const chooseImpact = (value: number, label: string) => {
    say({ from: "you", body: label }, { from: "bot", body: "Can you keep working?" });
    setDraft({ ...draft, impact: value });
    setStep("urgency");
  };

  const chooseUrgency = (value: number, label: string) => {
    say({ from: "you", body: label });
    const next = { ...draft, urgency: value };
    setDraft(next);
    void (pendingSuggestion ?? Promise.resolve(null)).then((found) => {
      askCategory(next, found);
    });
  };

  const chooseCategory = (use: boolean) => {
    const id = use ? (suggestion?.category_id ?? null) : null;
    say({ from: "you", body: use ? `Yes, ${categoryName(id)}` : "Let the help desk decide" });
    confirm({ ...draft, categoryId: id });
  };

  const submit = () => {
    const { service, impact, urgency } = draft;
    if (service === null || impact === null || urgency === null) return;
    say({ from: "you", body: "Report it" });
    setStep("sending");
    reportIncident.mutate(
      {
        title: draft.title,
        description: draft.description,
        service_id: service.id,
        impact,
        urgency,
        category_id: draft.categoryId,
        follow: draft.follow?.id ?? null,
      },
      {
        onSuccess: (result) => {
          const incident = result.incident;
          setReported(incident.id);
          say({
            from: "bot",
            body:
              result.followed != null
                ? `Done. You are now following ${result.followed.id}; I'll let you know when it is fixed.`
                : `Done: ${incident.id} is reported` +
                  (incident.priority ? ` as ${incident.priority}` : "") +
                  (result.assignment
                    ? " and a technician has it. You'll be notified as it progresses."
                    : "; the help desk will pick it up."),
          });
          setStep("done");
        },
        onError: (error) => {
          const message =
            error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
          say({ from: "bot", body: `I couldn't report it: ${message}` });
          setStep("confirm");
        },
      },
    );
  };

  const restart = () => {
    setMessages(greeting());
    setDraft(EMPTY);
    setText("");
    setReported(null);
    setSuggestion(null);
    setPendingSuggestion(null);
    classify.reset();
    similar.reset();
    setStep("title");
  };

  const choices = (
    options: readonly { label: string; onClick: () => void; primary?: boolean }[],
  ) => (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Answers">
      {options.map((o) => (
        <Button
          key={o.label}
          small
          variant={o.primary === true ? "primary" : "secondary"}
          onClick={o.onClick}
        >
          {o.label}
        </Button>
      ))}
    </div>
  );

  const best = similar.data?.candidates[0];
  const suggested = suggestion?.category_id ?? null;
  let answers: ReactNode = null;
  if (step === "title" || step === "details") {
    answers = (
      <form onSubmit={submitText} className="space-y-2">
        <label htmlFor="chat-answer" className="sr-only">
          Your answer
        </label>
        <textarea
          id="chat-answer"
          ref={input}
          rows={step === "details" ? 3 : 1}
          maxLength={step === "title" ? 200 : 5000}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) submitText(event);
          }}
          placeholder={step === "title" ? "e.g. The fee payment page fails" : "Type your answer"}
          className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink"
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <DictateButton
            label="Answer by voice"
            onText={(phrase) => {
              setText((current) => appendSentence(current, phrase));
            }}
          />
          <Button type="submit" variant="primary" small disabled={text.trim() === ""}>
            Send
          </Button>
        </div>
      </form>
    );
  } else if (step === "service") {
    answers = similar.isPending ? (
      <p className="text-sm text-muted">Checking for similar reports…</p>
    ) : (
      choices(
        rankServices(activeServices, `${draft.title} ${draft.description}`).map((s) => ({
          label: s.name,
          onClick: () => {
            chooseService(s);
          },
        })),
      )
    );
  } else if (step === "duplicate" && best) {
    answers = choices([
      {
        label: `Follow ${best.id}`,
        onClick: () => {
          chooseFollow(true);
        },
      },
      {
        label: "No, mine is different",
        onClick: () => {
          chooseFollow(false);
        },
      },
    ]);
  } else if (step === "impact") {
    answers = choices(
      IMPACT.map((o) => ({
        label: o.label,
        onClick: () => {
          chooseImpact(o.value, o.label);
        },
      })),
    );
  } else if (step === "urgency") {
    answers = choices(
      URGENCY.map((o) => ({
        label: o.label,
        onClick: () => {
          chooseUrgency(o.value, o.label);
        },
      })),
    );
  } else if (step === "category") {
    answers = choices([
      {
        label: `Yes, ${categoryName(suggested)}`,
        onClick: () => {
          chooseCategory(true);
        },
      },
      {
        label: "Let the help desk decide",
        onClick: () => {
          chooseCategory(false);
        },
      },
    ]);
  } else if (step === "confirm") {
    answers = choices([
      { label: "Report it", onClick: submit, primary: true },
      { label: "Start over", onClick: restart },
    ]);
  } else if (step === "sending") {
    answers = <p className="text-sm text-muted">Reporting…</p>;
  } else if (reported !== null) {
    answers = (
      <div className="flex flex-wrap gap-2">
        <Link
          to={incidentPath(portal, reported)}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white"
        >
          Open {reported}
        </Link>
        <Button small onClick={restart}>
          Report something else
        </Button>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        title="Report by chat"
        subtitle="Answer a few questions, by typing or by voice, and we file the incident for you."
      />
      <Card>
        <div
          ref={log}
          role="log"
          aria-live="polite"
          aria-label="Conversation"
          tabIndex={0}
          className="mb-4 max-h-[28rem] space-y-3 overflow-y-auto pr-1"
        >
          {messages.map((m, index) => (
            <div
              key={index}
              className={`flex ${m.from === "you" ? "justify-end" : "justify-start"}`}
            >
              <div
                data-from={m.from}
                className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm ${
                  m.from === "you"
                    ? "rounded-br-sm bg-accent text-white"
                    : "rounded-bl-sm border border-line bg-raised text-ink"
                }`}
              >
                <span className="sr-only">{m.from === "you" ? "You: " : "Help desk bot: "}</span>
                {m.body}
              </div>
            </div>
          ))}
        </div>
        {answers}
      </Card>
    </>
  );
}
