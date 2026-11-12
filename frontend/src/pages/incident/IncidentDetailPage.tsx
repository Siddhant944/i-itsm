import { useState, type SyntheticEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router";

import type { Schemas } from "../../api/client";
import {
  useAssignmentAdvice,
  useAudit,
  useCategories,
  useIncident,
  useIncidentAction,
  useNames,
  usePossibleDuplicates,
  useTeams,
  type Incident,
  type IncidentAction,
} from "../../api/hooks";
import { useAuth } from "../../auth/AuthContext";
import type { Me } from "../../auth/portal";
import { Badge, PriorityBadge, StatusBadge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { SelectField, TextArea } from "../../components/Field";
import { Modal } from "../../components/Modal";
import { SLAChip } from "../../components/SLAChip";
import { Card, ErrorState, QueryView, Skeleton } from "../../components/States";
import { useToasts } from "../../components/Toasts";
import {
  ALL_PRIORITIES,
  formatDateTime,
  levelLabel,
  priorityLabel,
  titleCase,
} from "../../lib/format";
import { usePortal } from "../../lib/usePortal";
import { incidentPath, PORTAL_HOME } from "../../shell/nav";
import { availableActions, pendingQuestion, timelineOf, type TimelineEntry } from "./actions";

type Dialog = "resolve" | "request" | "reject" | "verify" | "priority" | "category" | "cancel";

const ENTRY_TONE: Record<TimelineEntry["kind"], string> = {
  event: "bg-accent",
  note: "bg-slate-400",
  question: "bg-amber-500",
  answer: "bg-sky-500",
};

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs tracking-wide text-muted uppercase">{label}</dt>
      <dd className="mt-0.5 text-sm">{children}</dd>
    </div>
  );
}

function Timeline({ incident }: { incident: Incident }) {
  const names = useNames();
  return (
    <ol aria-label="Timeline" className="space-y-4">
      {timelineOf(incident).map((entry, index) => (
        <li key={`${entry.at}-${String(index)}`} className="flex gap-3">
          <span
            aria-hidden="true"
            className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${ENTRY_TONE[entry.kind]}`}
          />
          <div className="min-w-0">
            <p className="text-sm font-medium">
              {entry.title}
              {entry.actorId !== undefined && (
                <span className="font-normal text-muted"> · {names.person(entry.actorId)}</span>
              )}
            </p>
            <p className="text-xs text-muted">{formatDateTime(entry.at)}</p>
            {entry.body !== undefined && (
              <p className="mt-1 text-sm whitespace-pre-wrap">{entry.body}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** A single-textarea dialog: resolve, request information, reject. */
function TextDialog({
  title,
  label,
  hint,
  submitLabel,
  busy,
  onSubmit,
  onClose,
}: {
  title: string;
  label: string;
  hint?: string | undefined;
  submitLabel: string;
  busy: boolean;
  onSubmit: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  return (
    <Modal title={title} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(event: SyntheticEvent) => {
          event.preventDefault();
          if (text.trim() !== "") onSubmit(text.trim());
        }}
      >
        <TextArea
          label={label}
          hint={hint}
          value={text}
          required
          autoFocus
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={text.trim() === ""}>
            {submitLabel}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function VerifyDialog({
  busy,
  onSubmit,
  onClose,
}: {
  busy: boolean;
  onSubmit: (rating: number, comment: string) => void;
  onClose: () => void;
}) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  return (
    <Modal title="Confirm the fix" onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(event: SyntheticEvent) => {
          event.preventDefault();
          if (rating > 0) onSubmit(rating, comment.trim());
        }}
      >
        <fieldset>
          <legend className="mb-1 text-sm font-medium">How well was this handled?</legend>
          <div className="flex gap-2">
            {[1, 2, 3, 4, 5].map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={rating === value}
                aria-label={`${String(value)} out of 5`}
                onClick={() => {
                  setRating(value);
                }}
                className={`h-10 w-10 rounded-md border text-sm font-semibold ${rating >= value ? "border-accent bg-accent text-accent-ink" : "border-line bg-surface hover:bg-raised"}`}
              >
                {value}
              </button>
            ))}
          </div>
        </fieldset>
        <TextArea
          label="Anything to add? (optional)"
          value={comment}
          rows={3}
          onChange={(event) => {
            setComment(event.target.value);
          }}
        />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={rating === 0}>
            Confirm and rate
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function PriorityDialog({
  current,
  busy,
  onSubmit,
  onClose,
}: {
  current: Schemas["Priority"] | null;
  busy: boolean;
  onSubmit: (priority: Schemas["Priority"], reason: string) => void;
  onClose: () => void;
}) {
  const [priority, setPriority] = useState<Schemas["Priority"]>(current ?? "P3");
  const [reason, setReason] = useState("");
  return (
    <Modal title="Override the priority" onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(event: SyntheticEvent) => {
          event.preventDefault();
          if (reason.trim() !== "") onSubmit(priority, reason.trim());
        }}
      >
        <SelectField
          label="New priority"
          value={priority}
          onChange={(event) => {
            setPriority(event.target.value as Schemas["Priority"]);
          }}
        >
          {ALL_PRIORITIES.map((value) => (
            <option key={value} value={value}>
              {priorityLabel(value)}
            </option>
          ))}
        </SelectField>
        <TextArea
          label="Reason"
          hint="Required, and recorded in the audit log."
          value={reason}
          rows={3}
          required
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={reason.trim() === ""}>
            Override priority
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function CategoryDialog({
  current,
  busy,
  onSubmit,
  onClose,
}: {
  current: number | null;
  busy: boolean;
  onSubmit: (categoryId: number) => void;
  onClose: () => void;
}) {
  const categories = useCategories();
  const [categoryId, setCategoryId] = useState(current === null ? "" : String(current));
  return (
    <Modal title="Change the category" onClose={onClose}>
      <QueryView query={categories} loadingLabel="Loading categories">
        {(rows) => (
          <form
            className="space-y-4"
            onSubmit={(event: SyntheticEvent) => {
              event.preventDefault();
              if (categoryId !== "") onSubmit(Number(categoryId));
            }}
          >
            <SelectField
              label="Category"
              value={categoryId}
              onChange={(event) => {
                setCategoryId(event.target.value);
              }}
            >
              <option value="">Choose a category…</option>
              {rows.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </SelectField>
            <div className="flex justify-end gap-2">
              <Button onClick={onClose}>Cancel</Button>
              <Button type="submit" variant="primary" busy={busy} disabled={categoryId === ""}>
                Save category
              </Button>
            </div>
          </form>
        )}
      </QueryView>
    </Modal>
  );
}

/** The smart-assignment panel (§5.3): the ranked candidates, why, and one click to assign. */
function AssignmentPanel({
  incident,
  busy,
  onAssign,
}: {
  incident: Incident;
  busy: boolean;
  onAssign: (technicianId: number) => void;
}) {
  const advice = useAssignmentAdvice(incident.id, true);
  const names = useNames();
  return (
    <Card title="Assignment">
      {advice.isPending && <Skeleton rows={3} label="Ranking technicians" />}
      {advice.isError && <ErrorState error={advice.error} />}
      {advice.data !== undefined && (
        <>
          <p className="mb-3 text-xs text-muted">
            Ranked by the <strong>{titleCase(advice.data.strategy)}</strong> strategy.
          </p>
          {advice.data.ranked.length === 0 && (
            <p className="text-sm text-muted">
              Nobody available has the capacity for this incident right now.
            </p>
          )}
          <ol className="space-y-2">
            {advice.data.ranked.slice(0, 3).map((candidate, index) => {
              const current = candidate.technician_id === incident.assignee_id;
              return (
                <li
                  key={candidate.technician_id}
                  data-testid="candidate"
                  className="rounded-md border border-line px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium">
                      {String(index + 1)}. {names.person(candidate.technician_id)}
                    </p>
                    {current ? (
                      <Badge tone="accent">Current</Badge>
                    ) : (
                      <Button
                        small
                        disabled={busy}
                        onClick={() => {
                          onAssign(candidate.technician_id);
                        }}
                      >
                        Assign
                      </Button>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-muted">
                    Score {candidate.score.toFixed(2)} · {candidate.reasons.join(" · ")}
                  </p>
                </li>
              );
            })}
          </ol>
        </>
      )}
    </Card>
  );
}

/**
 * §6.2, BR-09: open incidents this one resembles. Confirming one cancels this incident as its
 * duplicate and its reporter then follows the other (D-005). Nothing happens without a click.
 */
function DuplicatePanel({
  incident,
  busy,
  onConfirm,
}: {
  incident: Incident;
  busy: boolean;
  onConfirm: (parentId: string) => void;
}) {
  const portal = usePortal();
  const found = usePossibleDuplicates(incident.id, true);
  const [chosen, setChosen] = useState<string | null>(null);
  return (
    <Card title="Possible duplicates">
      {found.isPending && <Skeleton rows={2} label="Comparing with open incidents" />}
      {found.isError && <ErrorState error={found.error} />}
      {found.data !== undefined && found.data.candidates.length === 0 && (
        <p className="text-sm text-muted">No open incident looks like this one.</p>
      )}
      {found.data !== undefined && found.data.candidates.length > 0 && (
        <>
          <p className="mb-3 text-xs text-muted">
            Compared by text, service and time (
            {found.data.provider === "tfidf" ? "offline TF-IDF" : found.data.provider}).
          </p>
          <ul className="space-y-2">
            {found.data.candidates.map((candidate) => (
              <li
                key={candidate.id}
                data-testid="possible-duplicate"
                className="rounded-md border border-line px-3 py-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <Link
                    className="text-sm font-medium underline"
                    to={incidentPath(portal, candidate.id)}
                  >
                    {candidate.id}
                  </Link>
                  <StatusBadge status={candidate.status} />
                </div>
                <p className="mt-1 text-sm">{candidate.title}</p>
                <p className="mt-1 text-xs text-muted">
                  {String(Math.round(candidate.score * 100))}% match ·{" "}
                  {candidate.reasons.join(" · ")}
                </p>
                <div className="mt-2 flex justify-end">
                  {chosen === candidate.id ? (
                    <span className="flex gap-2">
                      <Button
                        small
                        onClick={() => {
                          setChosen(null);
                        }}
                      >
                        Not this one
                      </Button>
                      <Button
                        small
                        variant="danger"
                        busy={busy}
                        onClick={() => {
                          onConfirm(candidate.id);
                        }}
                      >
                        Cancel {incident.id} as its duplicate
                      </Button>
                    </span>
                  ) : (
                    <Button
                      small
                      onClick={() => {
                        setChosen(candidate.id);
                      }}
                    >
                      Confirm duplicate…
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

/** The incident's hash-chained audit records (BR-10), for roles that may read the log. */
function AuditTrail({ incidentId }: { incidentId: string }) {
  const audit = useAudit(0, 50, incidentId);
  const names = useNames();
  return (
    <Card title="Audit trail">
      <QueryView
        query={audit}
        loadingLabel="Loading the audit trail"
        isEmpty={(page) => page.items.length === 0}
        empty={<p className="text-sm text-muted">No audit records for this incident.</p>}
      >
        {(page) => (
          <ul className="space-y-2 text-xs">
            {page.items.map((record) => (
              <li key={record.sequence} className="flex flex-wrap gap-x-2">
                <span className="font-mono text-muted">#{String(record.sequence)}</span>
                <span className="font-medium">{titleCase(record.action)}</span>
                <span className="text-muted">
                  {record.actor_id === null ? "System" : names.person(record.actor_id)} ·{" "}
                  {formatDateTime(record.occurred_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </QueryView>
    </Card>
  );
}

function Detail({ incident, me }: { incident: Incident; me: Me }) {
  const names = useNames();
  const toasts = useToasts();
  const { can } = useAuth();
  const portal = usePortal();
  const action = useIncidentAction(incident.id);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [note, setNote] = useState("");
  const [reply, setReply] = useState("");
  const teams = useTeams();
  const myTeam = teams.data?.find((team) => team.id === me.technician?.team_id);
  const allowed = availableActions(incident, me, myTeam?.member_ids ?? []);
  const question = pendingQuestion(incident);

  const run = (next: IncidentAction, done: string, after?: () => void) => {
    action.mutate(next, {
      onSuccess: () => {
        toasts.success(done);
        setDialog(null);
        after?.();
      },
      onError: (error) => {
        toasts.error(error);
      },
    });
  };
  const busy = action.isPending;
  const close = () => {
    setDialog(null);
  };

  return (
    <div className="space-y-5">
      <div>
        <Link to={PORTAL_HOME[portal]} className="text-sm text-muted underline">
          ← Back to the list
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm text-muted">{incident.id}</span>
          <StatusBadge status={incident.status} />
          <PriorityBadge priority={incident.priority} />
          <SLAChip sla={incident.sla} status={incident.status} />
          {incident.escalation_level > 0 && (
            <Badge tone="bad">Escalated · level {String(incident.escalation_level)}</Badge>
          )}
          {incident.priority_overridden && <Badge tone="warn">Priority overridden</Badge>}
          {incident.reopen_count > 0 && (
            <Badge tone="warn">Reopened ×{String(incident.reopen_count)}</Badge>
          )}
        </div>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">{incident.title}</h1>
      </div>

      {question !== null && allowed.provideInformation && (
        <div
          role="status"
          className="rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm"
        >
          <p className="font-medium">The technician needs more information from you</p>
          <p className="mt-1 whitespace-pre-wrap">{question}</p>
          <p className="mt-1 text-xs text-muted">The SLA clock is paused until you reply.</p>
        </div>
      )}
      {allowed.verify && (
        <div
          role="status"
          className="rounded-lg border border-emerald-500/50 bg-emerald-500/10 px-4 py-3 text-sm"
        >
          <p className="font-medium">A fix has been applied. Is it working for you?</p>
          <p className="mt-1 text-xs text-muted">
            If you do nothing, the incident closes automatically 72 hours after it was resolved.
          </p>
          <div className="mt-3 flex gap-2">
            <Button
              variant="primary"
              onClick={() => {
                setDialog("verify");
              }}
            >
              Yes, confirm the fix
            </Button>
            <Button
              onClick={() => {
                setDialog("reject");
              }}
            >
              No, it is not fixed
            </Button>
          </div>
        </div>
      )}

      {incident.duplicate_of !== null && incident.duplicate_of !== undefined && (
        <div
          role="status"
          data-testid="linked-duplicate"
          className="rounded-lg border border-line bg-raised px-4 py-3 text-sm"
        >
          <p className="font-medium">
            This is the same problem as {incident.duplicate_of.id} ({incident.duplicate_of.title}).
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            That incident is <StatusBadge status={incident.duplicate_of.status} /> and we will tell
            you when it is fixed.
          </p>
        </div>
      )}
      {incident.duplicate_count > 0 && (
        <p className="text-sm text-muted" data-testid="duplicate-count">
          {incident.duplicate_count === 1
            ? "1 other report is linked to this incident as a duplicate."
            : `${String(incident.duplicate_count)} other reports are linked to this incident as duplicates.`}
        </p>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card title="Description">
            <p className="text-sm whitespace-pre-wrap">{incident.description}</p>
          </Card>

          {incident.resolution !== null && (
            <Card title="Resolution">
              <p className="text-sm whitespace-pre-wrap">{incident.resolution.summary}</p>
              <p className="mt-2 text-xs text-muted">
                {names.person(incident.resolution.resolver_id)} ·{" "}
                {formatDateTime(incident.resolution.resolved_at)}
              </p>
            </Card>
          )}

          <Card title="Timeline">
            <Timeline incident={incident} />
          </Card>

          {allowed.provideInformation && (
            <Card title={question === null ? "Add information" : "Reply to the technician"}>
              <form
                className="space-y-3"
                onSubmit={(event: SyntheticEvent) => {
                  event.preventDefault();
                  if (reply.trim() === "") return;
                  run(
                    { kind: "information", text: reply.trim() },
                    "Your information was added.",
                    () => {
                      setReply("");
                    },
                  );
                }}
              >
                <TextArea
                  label="Your message"
                  rows={3}
                  value={reply}
                  onChange={(event) => {
                    setReply(event.target.value);
                  }}
                />
                <Button type="submit" variant="primary" busy={busy} disabled={reply.trim() === ""}>
                  Send
                </Button>
              </form>
            </Card>
          )}

          {allowed.note && (
            <Card title="Add a work note">
              <form
                className="space-y-3"
                onSubmit={(event: SyntheticEvent) => {
                  event.preventDefault();
                  if (note.trim() === "") return;
                  run({ kind: "note", text: note.trim() }, "Note added.", () => {
                    setNote("");
                  });
                }}
              >
                <TextArea
                  label="Note"
                  rows={3}
                  value={note}
                  onChange={(event) => {
                    setNote(event.target.value);
                  }}
                />
                <Button type="submit" busy={busy} disabled={note.trim() === ""}>
                  Add note
                </Button>
              </form>
            </Card>
          )}

          {can("audit:view") && <AuditTrail incidentId={incident.id} />}
        </div>

        <div className="space-y-5">
          <Card title="Actions">
            <div className="flex flex-col gap-2" data-testid="actions">
              {allowed.acknowledge && (
                <Button
                  variant="primary"
                  busy={busy}
                  onClick={() => {
                    run({ kind: "acknowledge" }, "Acknowledged. The response clock has stopped.");
                  }}
                >
                  Acknowledge
                </Button>
              )}
              {allowed.start && (
                <Button
                  variant="primary"
                  busy={busy}
                  onClick={() => {
                    run({ kind: "start" }, "Work started.");
                  }}
                >
                  Start work
                </Button>
              )}
              {allowed.resolve && (
                <Button
                  variant="primary"
                  onClick={() => {
                    setDialog("resolve");
                  }}
                >
                  Resolve
                </Button>
              )}
              {allowed.requestInformation && (
                <Button
                  onClick={() => {
                    setDialog("request");
                  }}
                >
                  Request information
                </Button>
              )}
              {allowed.resume && (
                <Button
                  variant="primary"
                  busy={busy}
                  onClick={() => {
                    run({ kind: "resume" }, "Work resumed. The SLA clock is running again.");
                  }}
                >
                  Resume work
                </Button>
              )}
              {allowed.close && (
                <Button
                  variant="primary"
                  busy={busy}
                  onClick={() => {
                    run({ kind: "close" }, "Incident closed.");
                  }}
                >
                  Close incident
                </Button>
              )}
              {allowed.overridePriority && (
                <Button
                  onClick={() => {
                    setDialog("priority");
                  }}
                >
                  Override priority
                </Button>
              )}
              {allowed.overrideCategory && (
                <Button
                  onClick={() => {
                    setDialog("category");
                  }}
                >
                  Change category
                </Button>
              )}
              {allowed.cancel && (
                <Button
                  variant="danger"
                  onClick={() => {
                    setDialog("cancel");
                  }}
                >
                  {incident.reporter_id === me.id ? "Withdraw incident" : "Cancel incident"}
                </Button>
              )}
              {!Object.values(allowed).some(Boolean) && (
                <p className="text-sm text-muted">Nothing to do on this incident right now.</p>
              )}
            </div>
          </Card>

          <Card title="Details">
            <dl className="grid grid-cols-2 gap-3">
              <Fact label="Service">{names.service(incident.service_id)}</Fact>
              <Fact label="Category">{names.category(incident.category_id)}</Fact>
              <Fact label="Reported by">{names.person(incident.reporter_id)}</Fact>
              <Fact label="Assigned to">{names.person(incident.assignee_id)}</Fact>
              <Fact label="Impact">{levelLabel(incident.impact)}</Fact>
              <Fact label="Urgency">{levelLabel(incident.urgency)}</Fact>
              <Fact label="Priority score">
                {incident.priority_score === null ? "—" : String(incident.priority_score)}
              </Fact>
              <Fact label="Reported">{formatDateTime(incident.created_at)}</Fact>
              {incident.sla !== null && (
                <>
                  <Fact label="Respond by">{formatDateTime(incident.sla.response_deadline)}</Fact>
                  <Fact label="Resolve by">{formatDateTime(incident.sla.resolution_deadline)}</Fact>
                </>
              )}
              {incident.parent_id !== null && (
                <Fact label="Duplicate of">
                  {/* BR-01: a reporter may not open someone else's incident, so no link. */}
                  {portal === "employee" ? (
                    incident.parent_id
                  ) : (
                    <Link className="underline" to={incidentPath(portal, incident.parent_id)}>
                      {incident.parent_id}
                    </Link>
                  )}
                </Fact>
              )}
            </dl>
          </Card>

          {allowed.confirmDuplicate && (
            <DuplicatePanel
              incident={incident}
              busy={busy}
              onConfirm={(parentId) => {
                run(
                  { kind: "confirm-duplicate", parentId },
                  `${incident.id} cancelled as a duplicate of ${parentId}; its reporter now follows ${parentId}.`,
                );
              }}
            />
          )}

          {allowed.reassign && (
            <AssignmentPanel
              incident={incident}
              busy={busy}
              onAssign={(technicianId) => {
                run(
                  { kind: "reassign", technicianId },
                  `Assigned to ${names.person(technicianId)}.`,
                );
              }}
            />
          )}
        </div>
      </div>

      {dialog === "resolve" && (
        <TextDialog
          title="Resolve the incident"
          label="What fixed it?"
          hint="The reporter sees this and is asked to confirm the fix."
          submitLabel="Mark as resolved"
          busy={busy}
          onClose={close}
          onSubmit={(summary) => {
            run({ kind: "resolve", summary }, "Resolved. The reporter has been asked to confirm.");
          }}
        />
      )}
      {dialog === "request" && (
        <TextDialog
          title="Request information"
          label="What do you need to know?"
          hint="The incident goes on hold and its SLA clock pauses until the reporter replies."
          submitLabel="Send request"
          busy={busy}
          onClose={close}
          onSubmit={(text) => {
            run({ kind: "request-information", text }, "Request sent. The SLA clock is paused.");
          }}
        />
      )}
      {dialog === "reject" && (
        <TextDialog
          title="The fix did not work"
          label="What is still wrong?"
          hint="The incident goes back to the technician."
          submitLabel="Reopen the incident"
          busy={busy}
          onClose={close}
          onSubmit={(reason) => {
            run({ kind: "reject", reason }, "Reopened. The technician has been told.");
          }}
        />
      )}
      {dialog === "verify" && (
        <VerifyDialog
          busy={busy}
          onClose={close}
          onSubmit={(rating, comment) => {
            run({ kind: "verify", rating, comment }, "Thank you. The fix is confirmed.");
          }}
        />
      )}
      {dialog === "priority" && (
        <PriorityDialog
          current={incident.priority}
          busy={busy}
          onClose={close}
          onSubmit={(priority, reason) => {
            run({ kind: "priority", priority, reason }, `Priority set to ${priority}.`);
          }}
        />
      )}
      {dialog === "category" && (
        <CategoryDialog
          current={incident.category_id}
          busy={busy}
          onClose={close}
          onSubmit={(categoryId) => {
            run({ kind: "category", categoryId }, "Category changed.");
          }}
        />
      )}
      {dialog === "cancel" && (
        <Modal title="Cancel this incident?" onClose={close}>
          <p className="text-sm text-muted">
            A cancelled incident cannot be reopened. Report a new one if the problem returns.
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={close}>Keep it open</Button>
            <Button
              variant="danger"
              busy={busy}
              onClick={() => {
                run({ kind: "cancel" }, "Incident cancelled.");
              }}
            >
              Cancel incident
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}

/** One incident, for whichever portal the reader is in. */
export function IncidentDetailPage() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const incident = useIncident(id);
  if (user === null) return null;
  return (
    <QueryView query={incident} loadingLabel="Loading the incident">
      {(found) => <Detail incident={found} me={user} />}
    </QueryView>
  );
}
