"""The facade every incident route calls (blueprint §2, §5, §7).

Pattern: Facade. Problem solved: reporting an incident touches the classifier, the priority
strategy, the SLA policy book, the assignment strategy, the audit chain and the notification
dispatcher. A router should not orchestrate six collaborators, so it calls one method here and
maps the result; the order of the steps lives in one place and cannot drift between endpoints.

Every method follows the same shape:

1. load the aggregate and check who is asking (BR-01, BR-02, BR-03);
2. let the aggregate decide whether the change is legal (the State pattern raises if not);
3. save it, write the audit records the aggregate's events describe — same transaction — commit;
4. hand the events to the post-commit dispatcher, which notifies afterwards (§5.4).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from app.core.clock import Clock
from app.domain.access import (
    ensure_can_cancel,
    ensure_can_view,
    ensure_can_work,
    ensure_is_reporter,
)
from app.domain.assignment import (
    AssignmentRequest,
    AssignmentStrategy,
    Candidate,
    CandidateScore,
    SmartStrategy,
    check_capacity,
)
from app.domain.audit import AuditAction
from app.domain.catalogue import Category, ITService, required_skills_for
from app.domain.dependency_graph import (
    LIVE_STATUSES,
    CorrelationReport,
    DependencyGraph,
    correlate,
)
from app.domain.errors import (
    DuplicateIncidentError,
    InvalidUserInputError,
    ServiceNotFoundError,
    TechnicianUnavailableError,
    UnauthorizedOperationError,
)
from app.domain.events import (
    CategoryChanged,
    DomainEvent,
    IncidentCreated,
    IncidentStateChanged,
    PriorityChanged,
    WorkNoteAdded,
)
from app.domain.incident import CancelReason, Incident, IncidentFactory
from app.domain.permissions import Permission
from app.domain.ports import AIAdvisor, CategoryInfo, Classification
from app.domain.priority import Priority, PriorityStrategy, WeightedProductPriorityStrategy
from app.domain.repositories import UnitOfWork
from app.domain.risk import HistoricalRiskEstimator, RiskEstimate
from app.domain.search import MAX_PAGE_SIZE, IncidentQuery
from app.domain.states import IncidentStatus
from app.domain.users import Technician, User
from app.services.audit import AuditService
from app.services.dispatcher import PostCommitDispatcher
from app.services.duplicates import (
    COMPARABLE_STATUSES,
    DuplicateCandidate,
    DuplicateCheck,
    DuplicateDetector,
)
from app.services.resolution_advisor import ResolutionAdvisor, ResolutionSuggestion

#: A change applied to a loaded incident, once the caller has been allowed to make it.
Change = Callable[[Incident], object]

#: Which audit action an incident event becomes. A new event type must be added here.
AUDIT_FOR_EVENT: Mapping[type[DomainEvent], AuditAction] = {
    IncidentCreated: AuditAction.INCIDENT_CREATED,
    IncidentStateChanged: AuditAction.INCIDENT_STATE_CHANGED,
    CategoryChanged: AuditAction.CATEGORY_OVERRIDDEN,
    WorkNoteAdded: AuditAction.INCIDENT_NOTE_ADDED,
}


def audit_action_for(event: DomainEvent) -> AuditAction | None:
    """The action to record for ``event``, or None for an event the trail does not keep.

    A priority change with no actor is the engine assessing the incident; one with an actor is
    a human override, which §7 BR-05 wants recorded as such.
    """
    if isinstance(event, PriorityChanged):
        return (
            AuditAction.PRIORITY_ASSESSED
            if event.actor_id is None
            else AuditAction.PRIORITY_OVERRIDDEN
        )
    return AUDIT_FOR_EVENT.get(type(event))


@dataclass(frozen=True, slots=True)
class ReportedIncident:
    """What reporting an incident produced, including the advice the reporter may override."""

    incident: Incident
    suggestion: Classification | None
    assignment: CandidateScore | None
    #: Classified, but no technician had capacity, so the Team Lead picks it up (§8).
    queued_for_team_lead: bool = False
    #: Nobody could say which category it belongs to, so a human classifies it first (§4).
    needs_triage: bool = False
    #: Open incidents this one resembles (§6.2); the technician confirms or ignores them.
    possible_duplicates: tuple[DuplicateCandidate, ...] = ()
    #: The incident the reporter chose to follow instead; this one is then its duplicate.
    followed: Incident | None = None


@dataclass(frozen=True, slots=True)
class AssignmentAdvice:
    """The ranked technicians, so the UI can show the top three with their reasons (§6)."""

    ranked: tuple[CandidateScore, ...]
    strategy: str

    @property
    def best(self) -> CandidateScore | None:
        return self.ranked[0] if self.ranked else None


class IncidentService:
    """Everything a caller can do to an incident, with the rules applied in one order."""

    def __init__(
        self,
        uow: UnitOfWork,
        clock: Clock,
        *,
        dispatcher: PostCommitDispatcher | None = None,
        advisor: AIAdvisor | None = None,
        priority_strategy: PriorityStrategy | None = None,
        assignment_strategy: AssignmentStrategy | None = None,
        duplicates: DuplicateDetector | None = None,
        resolutions: ResolutionAdvisor | None = None,
    ) -> None:
        self.__uow = uow
        self.__clock = clock
        self.__dispatcher = dispatcher or PostCommitDispatcher()
        self.__advisor = advisor
        self.__priority = priority_strategy or WeightedProductPriorityStrategy()
        self.__assignment = assignment_strategy or SmartStrategy()
        self.__audit = AuditService(uow.audit, clock)
        self.__duplicates = duplicates or DuplicateDetector(uow, clock)
        self.__resolutions = resolutions or ResolutionAdvisor(uow, clock)

    # ------------------------------------------------------------ reading
    def get(self, actor: User, incident_id: str) -> Incident:
        """One incident, if the caller may see it (BR-01)."""
        incident = self.__uow.incidents.get(incident_id)
        ensure_can_view(actor, incident, self.__team_of(actor))
        return incident

    def my_incidents(self, actor: User) -> tuple[Incident, ...]:
        """What the caller reported (BR-01)."""
        return self.__uow.incidents.list_by_reporter(actor.id)

    def my_queue(self, actor: User) -> tuple[Incident, ...]:
        """What the caller is carrying as a technician."""
        if not actor.can(Permission.INCIDENT_VIEW_ASSIGNED):
            raise UnauthorizedOperationError("Your role has no incident queue.")
        return self.__uow.incidents.list_for_assignee(actor.id)

    def duplicate_links(self, incident: Incident) -> tuple[Incident | None, int]:
        """The incident this one was linked to as a duplicate, and how many are linked to it.

        D-005: the link is the subscription, so the reporter of a duplicate may see where
        their report went and how it stands — its id, title and status, nothing more.
        """
        parent = None
        if incident.parent_id is not None and incident.cancel_reason is CancelReason.DUPLICATE:
            parent = self.__uow.incidents.get(incident.parent_id)
        return parent, len(self.__uow.incidents.duplicates_of(incident.id))

    # ------------------------------------------------------------ reporting
    def classify_text(self, text: str) -> Classification | None:
        """The category suggestion shown while the reporter types (§6.1); never applied alone."""
        if self.__advisor is None:
            return None
        return self.__advisor.classify(text, self.__category_infos())

    def similar_incidents(
        self, actor: User, *, title: str, description: str, service_id: int | None
    ) -> DuplicateCheck:
        """Open incidents that look like what the reporter is typing (§6.2). Advice only."""
        self.__require(actor, Permission.INCIDENT_CREATE)
        return self.__duplicates.check(
            title=title,
            description=description,
            service_id=service_id,
            reported_at=self.__clock.now(),
        )

    def possible_duplicates(self, actor: User, incident_id: str) -> DuplicateCheck:
        """What an open incident may be a duplicate of, for the technician to confirm (§6.2)."""
        self.__require(actor, Permission.INCIDENT_CONFIRM_DUPLICATE)
        incident = self.get(actor, incident_id)
        if incident.status not in COMPARABLE_STATUSES:
            return DuplicateCheck((), "")
        return self.__duplicates.check(
            title=incident.title,
            description=incident.description,
            service_id=incident.service_id,
            reported_at=incident.created_at,
            exclude_id=incident.id,
        )

    def correlation(self, actor: User, incident_id: str) -> CorrelationReport:
        """§6.2: open incidents related to this one through the service dependency graph.

        Staff only: the report names other people's incidents, which BR-01 keeps from
        employees.
        """
        self.__require(actor, Permission.INCIDENT_VIEW_ASSIGNED)
        incident = self.get(actor, incident_id)
        graph = DependencyGraph(self.__uow.catalogue.services())
        related = {
            reach.service_id
            for reach in (
                *graph.upstream(incident.service_id),
                *graph.downstream(incident.service_id),
            )
        }
        if not related:
            return CorrelationReport((), ())
        page = self.__uow.incidents.search(
            IncidentQuery(
                statuses=tuple(LIVE_STATUSES),
                service_ids=tuple(sorted(related)),
                limit=MAX_PAGE_SIZE,
            ),
            self.__clock.now(),
        )
        return correlate(incident, graph, page.items)

    def risk(self, actor: User, incident_id: str) -> RiskEstimate | None:
        """§6.3: how likely this incident is to breach its resolution target, and why.

        None when there is nothing to forecast: no SLA clock yet, the clock has stopped
        (resolved, closed or cancelled), it is paused waiting for the reporter, or the
        incident has no category or priority to compare it with.
        """
        incident = self.get(actor, incident_id)
        clock = incident.sla_clock
        if (
            clock is None
            or clock.is_stopped
            or clock.is_paused
            or incident.category_id is None
            or incident.priority is None
        ):
            return None
        category = self.__category(incident.category_id)
        estimator = HistoricalRiskEstimator(
            self.__uow.incidents.resolution_durations(category.id, incident.priority),
            label=f"{incident.priority.value} {category.name}",
        )
        # A running clock measures against its live target (D-017 freezes it only at RESOLVED).
        return estimator.estimate(
            clock.resolution_elapsed(self.__clock.now()), clock.target.resolution
        )

    def suggested_resolution(self, actor: User, incident_id: str) -> ResolutionSuggestion:
        """§6.1: how the most similar resolved incidents were fixed. Advice for staff only."""
        self.__require(actor, Permission.INCIDENT_VIEW_ASSIGNED)
        return self.__resolutions.suggest(self.get(actor, incident_id))

    def service_names(self) -> Mapping[int, str]:
        """Every service's name, retired ones included, for the words of a hint."""
        return {service.id: service.name for service in self.__uow.catalogue.services()}

    def confirm_duplicate(self, actor: User, incident_id: str, parent_id: str) -> Incident:
        """BR-09: cancel ``incident_id`` as a duplicate of ``parent_id``.

        Its reporter is from then on told about the parent (D-005). Whoever may work the
        incident may confirm it; the parent only has to exist and still be open, because the
        "possible duplicate" panel has already shown its id and title.
        """
        self.__require(actor, Permission.INCIDENT_CONFIRM_DUPLICATE)

        def change(incident: Incident) -> None:
            parent = self.__duplicate_parent(incident, parent_id)
            incident.cancel(actor.id, self.__clock, CancelReason.DUPLICATE, parent.id)

        return self.__work(actor, incident_id, change)

    def report(
        self,
        actor: User,
        *,
        title: str,
        description: str,
        service_id: int,
        impact: int,
        urgency: int,
        category_id: int | None = None,
        follow: str | None = None,
    ) -> ReportedIncident:
        """Report an incident, then classify, prioritise, set its SLA and assign it.

        ``category_id`` is the reporter's or the AI's choice, confirmed by the caller. When it
        is omitted the advisor suggests one and the suggestion is applied, with its confidence
        kept so the UI can show what happened and let a technician override it.

        BR-09: the same reporter's near-identical report within 30 minutes is refused with
        ``DuplicateIncidentError``. ``follow`` names an open incident the form suggested;
        the report is then recorded and at once linked to it as a duplicate, which is what
        subscribes the reporter to it (D-005).
        """
        self.__require(actor, Permission.INCIDENT_CREATE)
        service = self.__service(service_id, offered=True)
        # Bad input is refused as bad input before anything is compared with anything.
        category = None if category_id is None else self.__category(category_id, offered=True)
        check = self.__duplicates.check(
            title=title,
            description=description,
            service_id=service_id,
            reported_at=self.__clock.now(),
        )
        for candidate in check.candidates:
            if candidate.incident.reporter_id == actor.id and self.__duplicates.thresholds.rejects(
                candidate.score, candidate.gap
            ):
                raise DuplicateIncidentError(candidate.incident.id)
        followed = None if follow is None else self.__followed(check, follow)

        incident = IncidentFactory.create(
            sequence=self.__uow.incidents.next_sequence(self.__clock.now().year),
            clock=self.__clock,
            reporter_id=actor.id,
            title=title,
            description=description,
            service_id=service_id,
            impact=impact,
            urgency=urgency,
        )

        # The row must exist before anything audits it: audit_log.incident_id is a real
        # foreign key, and §4's opening steps all write audit records about this incident.
        self.__uow.incidents.add(incident)
        self.__duplicates.remember(incident.id, check)
        if check.candidates:
            # §6.1: every AI decision is audited, including one nobody acts on.
            self.__audit.record(
                AuditAction.DUPLICATE_SUGGESTED,
                incident_id=incident.id,
                details={
                    "provider": check.provider,
                    "candidates": [
                        {"id": c.incident.id, "score": round(c.score.total, 3)}
                        for c in check.candidates
                    ],
                },
            )
        if followed is not None:
            incident.cancel(actor.id, self.__clock, CancelReason.DUPLICATE, followed.id)
            self.__uow.incidents.save(incident)
            self.__commit(incident)
            return ReportedIncident(
                incident, None, None, possible_duplicates=check.candidates, followed=followed
            )

        suggestion = None
        if category is None:
            suggestion = self.classify_text(f"{title}\n{description}")
            if suggestion is not None:
                # §6.1: every AI decision is audited — which advisor, what it chose, how sure.
                self.__audit.record(
                    AuditAction.AI_CLASSIFIED,
                    incident_id=incident.id,
                    details={
                        "source": suggestion.source,
                        "category_id": suggestion.category_id,
                        "confidence": round(suggestion.confidence, 3),
                    },
                )
            if suggestion is not None and suggestion.category_id is not None:
                category = self.__category(suggestion.category_id)

        self.__prioritise(incident, service, category)

        chosen, queued = None, False
        if category is None:
            # §4 runs NEW -> CLASSIFIED -> ASSIGNED, so an unclassified incident waits for a
            # human rather than being assigned to a technician nobody chose.
            self.__audit.record(
                AuditAction.INCIDENT_STATE_CHANGED,
                incident_id=incident.id,
                details={"needs_triage": True, "reason": "no category could be determined"},
            )
        else:
            incident.classify(category.id, None, self.__clock)
            chosen, queued = self.__auto_assign(incident)

        self.__uow.incidents.save(incident)
        self.__commit(incident)
        return ReportedIncident(
            incident,
            suggestion,
            chosen,
            queued,
            needs_triage=category is None,
            possible_duplicates=check.candidates,
        )

    # ------------------------------------------------------------ technician actions
    def acknowledge(self, actor: User, incident_id: str) -> Incident:
        """BR-02: only the assignee, the escalation owner or an admin."""
        return self.__work(actor, incident_id, lambda i: i.acknowledge(actor.id, self.__clock))

    def start(self, actor: User, incident_id: str) -> Incident:
        return self.__work(actor, incident_id, lambda i: i.start(actor.id, self.__clock))

    def add_note(self, actor: User, incident_id: str, text: str) -> Incident:
        return self.__work(actor, incident_id, lambda i: i.add_note(actor.id, self.__clock, text))

    def request_information(self, actor: User, incident_id: str, question: str) -> Incident:
        """Ask the reporter a question; the resolution clock pauses (BR-07)."""
        return self.__work(actor, incident_id, lambda i: i.hold(actor.id, self.__clock, question))

    def resume(self, actor: User, incident_id: str) -> Incident:
        return self.__work(actor, incident_id, lambda i: i.resume(actor.id, self.__clock))

    def resolve(self, actor: User, incident_id: str, summary: str) -> Incident:
        """BR-04: a resolution summary is required."""
        return self.__work(actor, incident_id, lambda i: i.resolve(actor.id, self.__clock, summary))

    def reassign(self, actor: User, incident_id: str, technician_id: int) -> Incident:
        """Hand the incident to another technician, respecting the capacity cap (BR-06)."""
        self.__require(actor, Permission.INCIDENT_REASSIGN)

        def change(incident: Incident) -> None:
            technician = self.__technician(technician_id)
            if not technician.available or not technician.active:
                raise TechnicianUnavailableError(
                    f"{technician.full_name} is not available for assignment."
                )
            if incident.priority is not None and technician_id != incident.assignee_id:
                # workloads() already counts every open incident this technician holds, so the
                # one being moved would otherwise be charged to them twice.
                check_capacity(
                    self.__uow.incidents.workloads().get(technician_id, 0), incident.priority
                )
            incident.assign(technician_id, actor.id, self.__clock)

        return self.__work(actor, incident_id, change)

    def override_priority(
        self, actor: User, incident_id: str, priority: Priority, reason: str
    ) -> Incident:
        """BR-05: an override needs a reason and is audited."""
        self.__require(actor, Permission.INCIDENT_OVERRIDE_PRIORITY)

        def change(incident: Incident) -> None:
            incident.override_priority(priority, reason, actor.id, self.__clock)
            self.__apply_sla(incident)

        return self.__work(actor, incident_id, change)

    def override_category(self, actor: User, incident_id: str, category_id: int) -> Incident:
        """Correct the category the AI or the reporter chose (§6.1: nothing is silent)."""
        self.__require(actor, Permission.INCIDENT_OVERRIDE_CATEGORY)

        def change(incident: Incident) -> None:
            category = self.__category(category_id, offered=True)
            if incident.category_id is None:
                incident.classify(category.id, actor.id, self.__clock)
            else:
                incident.recategorise(category.id, actor.id, self.__clock)

        return self.__work(actor, incident_id, change)

    # ------------------------------------------------------------ reporter actions
    def provide_information(self, actor: User, incident_id: str, answer: str) -> Incident:
        """The reporter answers a question; an incident on hold resumes (D-006)."""
        incident = self.__uow.incidents.get(incident_id)
        ensure_is_reporter(actor, incident)
        incident.provide_info(actor.id, self.__clock, answer)
        return self.__save(incident)

    def verify(self, actor: User, incident_id: str, rating: int, comment: str = "") -> Incident:
        """BR-03: only the reporter verifies the fix."""
        incident = self.__uow.incidents.get(incident_id)
        ensure_is_reporter(actor, incident)
        incident.verify(actor.id, self.__clock, rating, comment)
        return self.__save(incident)

    def reject(self, actor: User, incident_id: str, reason: str) -> Incident:
        """BR-03, BR-04: only the reporter rejects, and only from RESOLVED."""
        incident = self.__uow.incidents.get(incident_id)
        ensure_is_reporter(actor, incident)
        incident.reject(actor.id, self.__clock, reason)
        return self.__save(incident)

    def cancel(
        self,
        actor: User,
        incident_id: str,
        reason: CancelReason = CancelReason.WITHDRAWN,
        duplicate_of: str | None = None,
    ) -> Incident:
        incident = self.__uow.incidents.get(incident_id)
        ensure_can_cancel(actor, incident)
        if duplicate_of is not None:
            # 404 rather than a dangling link, and BR-01 rather than a link into someone
            # else's incident: D-005 makes parent_id the subscription, so a link the caller
            # may not see would become a read path in P4.1.
            parent = self.__duplicate_parent(incident, duplicate_of)
            ensure_can_view(actor, parent, self.__team_of(actor))
        incident.cancel(actor.id, self.__clock, reason, duplicate_of)
        return self.__save(incident)

    def close(self, actor: User, incident_id: str) -> Incident:
        self.__require(actor, Permission.INCIDENT_WORK)
        return self.__work(actor, incident_id, lambda i: i.close(actor.id, self.__clock))

    # ------------------------------------------------------------ assignment advice
    def assignment_advice(self, incident: Incident) -> AssignmentAdvice:
        """Rank the technicians for an incident, with the reasons the UI shows (§5.3, §6)."""
        if incident.priority is None:
            return AssignmentAdvice((), self.__assignment.name)
        service = self.__service(incident.service_id)
        category = None if incident.category_id is None else self.__category(incident.category_id)
        request = AssignmentRequest(
            priority=incident.priority,
            required_skills=required_skills_for(
                category, service, self.__uow.catalogue.skill_names()
            ),
            service_id=incident.service_id,
        )
        try:
            # select() applies the BR-06 filter (available, active, under the 10-point cap)
            # before ranking; nobody eligible is an empty list here, and the caller decides
            # whether that is an error or a queue for the Team Lead.
            ranked = self.__assignment.select(request, self.__candidates(incident.service_id))
        except TechnicianUnavailableError:
            ranked = ()
        return AssignmentAdvice(ranked, self.__assignment.name)

    # ------------------------------------------------------------ internals
    def __work(self, actor: User, incident_id: str, change: Change) -> Incident:
        """Load, check BR-02, apply ``change``, save."""
        incident = self.__uow.incidents.get(incident_id)
        ensure_can_work(actor, incident, self.__team_of(actor))
        change(incident)
        return self.__save(incident)

    def __save(self, incident: Incident) -> Incident:
        self.__uow.incidents.save(incident)
        self.__commit(incident)
        return incident

    def __commit(self, incident: Incident) -> None:
        """Audit in the same transaction, then notify after it (blueprint §5.4)."""
        events = incident.pull_events()
        for event in events:
            action = audit_action_for(event)
            if action is None:
                continue
            self.__audit.record(
                action,
                actor_id=event.actor_id,
                incident_id=event.incident_id,
                details=_details(event),
            )
        try:
            self.__uow.commit()
        except Exception:
            self.__dispatcher.discard()
            raise
        self.__dispatcher.enqueue(events)
        self.__dispatcher.dispatch()

    def __prioritise(
        self, incident: Incident, service: ITService, category: Category | None
    ) -> None:
        assessment = self.__priority.assess(
            incident.impact,
            incident.urgency,
            service.criticality,
            category.minimum_priority if category else None,
        )
        incident.prioritise(assessment, self.__clock)
        self.__apply_sla(incident)

    def __apply_sla(self, incident: Incident) -> None:
        """Set or retarget the SLA clock for the incident's current priority (§5.2, D-016)."""
        if incident.priority is None:
            return
        service = self.__service(incident.service_id)
        target, used_default = self.__uow.catalogue.policy_book().target_or_default(
            service.sla_tier, incident.priority
        )
        incident.apply_sla(target)
        if used_default:
            self.__audit.record(
                AuditAction.CONFIGURATION_CHANGED,
                incident_id=incident.id,
                details={
                    "missing_sla_policy": f"{service.sla_tier.value}/{incident.priority.value}",
                    "applied": "gold default (D-016)",
                },
            )

    def __auto_assign(self, incident: Incident) -> tuple[CandidateScore | None, bool]:
        """Pick a technician, or leave the incident for the Team Lead (BR-06, §8)."""
        advice = self.assignment_advice(incident)
        chosen = advice.best
        if chosen is None:
            # §8: an automatic assignment with nobody available is queued, not an error.
            self.__audit.record(
                AuditAction.INCIDENT_STATE_CHANGED,
                incident_id=incident.id,
                details={"queued_for_team_lead": True, "reason": "no technician with capacity"},
            )
            return None, True
        incident.assign(chosen.technician_id, None, self.__clock)
        return chosen, False

    def __duplicate_parent(self, incident: Incident, parent_id: str) -> Incident:
        """The incident ``incident`` may be linked to, or the reason it may not (BR-09)."""
        parent = self.__uow.incidents.get(parent_id)
        problem = None
        if parent.id == incident.id:
            problem = "An incident cannot be a duplicate of itself."
        elif parent.parent_id is not None and parent.cancel_reason is CancelReason.DUPLICATE:
            problem = f"{parent.id} is itself a duplicate of {parent.parent_id}; link to that."
        elif parent.status is IncidentStatus.CANCELLED:
            problem = f"{parent.id} was cancelled, so nothing can be linked to it."
        elif self.__uow.incidents.duplicates_of(incident.id):
            problem = (
                f"Other reports are already linked to {incident.id}; link {parent.id} to it "
                "instead."
            )
        if problem is not None:
            raise InvalidUserInputError({"duplicate_of": problem})
        return parent

    @staticmethod
    def __followed(check: DuplicateCheck, incident_id: str) -> Incident:
        """The suggested incident the reporter chose to follow; only a suggestion will do.

        Following is how an employee comes to hear about someone else's incident, so it is
        limited to the ones the similarity check itself put in front of them (BR-01).
        """
        for candidate in check.candidates:
            if candidate.incident.id == incident_id:
                return candidate.incident
        raise InvalidUserInputError(
            {"follow": f"{incident_id} is not an open incident similar to this report."}
        )

    def __candidates(self, service_id: int) -> tuple[Candidate, ...]:
        loads = self.__uow.incidents.workloads()
        fixes = self.__uow.incidents.past_fixes(service_id)
        return tuple(
            Candidate(
                technician=technician,
                load=loads.get(technician.id, 0),
                past_fixes=fixes.get(technician.id, 0),
            )
            for technician in self.__uow.users.technicians()
        )

    def __category_infos(self) -> Sequence[CategoryInfo]:
        return [
            CategoryInfo(category.id, category.name, category.keywords)
            for category in self.__uow.catalogue.categories(active_only=True)
        ]

    def __team_of(self, actor: User) -> frozenset[int]:
        """The technicians in the caller's team, for the Team Lead rules (D-004)."""
        if not isinstance(actor, Technician) or actor.team_id is None:
            return frozenset()
        return frozenset(self.__uow.catalogue.get_team(actor.team_id).member_ids)

    def __service(self, service_id: int, *, offered: bool = False) -> ITService:
        """A service by id. ``offered`` insists it can still be reported against.

        Only reporting asks for that: an incident already open on a service that has since
        been retired must stay workable, or retiring a service would strand its incidents.
        """
        service = self.__uow.catalogue.get_service(service_id)
        if offered and not service.active:
            raise ServiceNotFoundError(f"{service.name} is no longer offered.")
        return service

    def __category(self, category_id: int, *, offered: bool = False) -> Category:
        """A category by id; ``offered`` refuses a retired one for a new choice."""
        category = self.__uow.catalogue.get_category(category_id)
        if offered and not category.active:
            raise InvalidUserInputError({"category_id": f"{category.name} is no longer offered."})
        return category

    def __technician(self, technician_id: int) -> Technician:
        user = self.__uow.users.get(technician_id)
        if not isinstance(user, Technician):
            raise InvalidUserInputError({"technician_id": "That user is not a technician."})
        return user

    def __require(self, actor: User, permission: Permission) -> None:
        if not actor.can(permission):
            raise UnauthorizedOperationError(f"Your role may not {permission.value}.")


def _details(event: DomainEvent) -> dict[str, object]:
    """The event's own fields, as JSON-safe values for the audit record."""
    if isinstance(event, IncidentStateChanged):
        return {
            "from": event.from_status.value,
            "to": event.to_status.value,
            "description": event.description,
        }
    if isinstance(event, PriorityChanged):
        return {
            "from": event.old_priority.value if event.old_priority else None,
            "to": event.new_priority.value,
            "reason": event.reason,
        }
    if isinstance(event, CategoryChanged):
        return {"from": event.old_category_id, "to": event.new_category_id}
    if isinstance(event, WorkNoteAdded):
        return {"kind": event.kind}
    if isinstance(event, IncidentCreated):
        return {"title": event.title}
    return {}
