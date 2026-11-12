"""The SLA monitor (blueprint §5.2, §5.5, BR-03, BR-08, D-003).

One tick does four things, in this order:

1. warn once when an incident reaches 75 % of a target;
2. record a breach once when a target is passed;
3. ask the escalation chain whether the incident should move up a level, and move it;
4. close resolutions the reporter never answered, after 72 hours.

"Once" is the whole difficulty: a tick runs every 30 clock seconds, so every step has to be
idempotent. Each warning and each breach is written to ``sla_violations`` keyed by the
incident, the kind and the incident's reopen count, and the row is what stops a second tick
reporting the same thing. The escalation level on the incident does the same job for step 3.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from types import MappingProxyType

from app.core.clock import Clock
from app.domain.audit import AuditAction
from app.domain.catalogue import fallback_lead
from app.domain.errors import ITSMError
from app.domain.escalation import MAX_MISSED_TARGETS as MAX_ESCALATION_LEVEL
from app.domain.escalation import EscalationContext, decide_escalation
from app.domain.incident import Incident
from app.domain.notifications import NotificationEvent
from app.domain.permissions import Role, escalation_level
from app.domain.repositories import UnitOfWork
from app.domain.sla import SLAClock, SLAStatus, SLAViolation, ViolationKind
from app.domain.states import OPEN_STATUSES, IncidentStatus
from app.domain.users import Technician, User
from app.services.audit import AuditService

logger = logging.getLogger(__name__)

#: How the monitor tells someone: the NotificationService's own ``notify`` (§5.4).
NotifyFn = Callable[[NotificationEvent, Incident, str], object]

#: D-003: the monitor ticks every 30 seconds of *clock* time, so under the demo's ×10 clock it
#: runs every 3 real seconds and a P1's 5-minute response window passes in 30.
TICK_INTERVAL = timedelta(seconds=30)
#: BR-03: a resolution the reporter never answers closes itself after this long.
AUTO_CLOSE_AFTER = timedelta(hours=72)


@dataclass(frozen=True, slots=True)
class Escalation:
    """Who an incident was handed to, so §5.4 can tell them after the commit."""

    incident_id: str
    owner_id: int
    level: int
    reason: str


@dataclass(frozen=True, slots=True)
class TickReport:
    """What one tick did, so a test or the demo can see it rather than infer it."""

    warned: tuple[SLAViolation, ...] = field(default_factory=tuple)
    breached: tuple[SLAViolation, ...] = field(default_factory=tuple)
    escalations: tuple[Escalation, ...] = field(default_factory=tuple)
    auto_closed: tuple[str, ...] = field(default_factory=tuple)

    @property
    def changed(self) -> tuple[str, ...]:
        """Every incident this tick touched, once each, for live updates (P4.8)."""
        ids = [
            *(v.incident_id for v in self.warned),
            *(v.incident_id for v in self.breached),
            *self.escalated,
            *self.auto_closed,
        ]
        return tuple(dict.fromkeys(ids))

    @property
    def escalated(self) -> tuple[str, ...]:
        """The ids that moved up a level."""
        return tuple(step.incident_id for step in self.escalations)

    @property
    def did_nothing(self) -> bool:
        return not (self.warned or self.breached or self.escalations or self.auto_closed)

    @property
    def summary(self) -> str:
        return (
            f"tick: {len(self.warned)} warned, {len(self.breached)} breached, "
            f"{len(self.escalated)} escalated, {len(self.auto_closed)} auto-closed"
        )


class SLAMonitor:
    """Watches the clocks and acts on what it finds. One ``tick()`` is the whole of it."""

    def __init__(
        self,
        uow: UnitOfWork,
        clock: Clock,
        *,
        notify: NotifyFn | None = None,
    ) -> None:
        self.__uow = uow
        self.__clock = clock
        self.__notify = notify
        self.__audit = AuditService(uow.audit, clock)

    def tick(self) -> TickReport:
        """Run one pass. Safe to call again immediately: everything it does is recorded."""
        now = self.__clock.now()
        warned: list[SLAViolation] = []
        breached: list[SLAViolation] = []
        escalations: list[Escalation] = []

        for incident in self.__uow.incidents.needing_sla_attention(now):
            clock = incident.sla_clock
            if clock is None:  # pragma: no cover - the query only returns incidents with one
                continue
            warned.extend(self.__record(incident, clock, now, breach=False))
            breached.extend(self.__record(incident, clock, now, breach=True))
            step = self.__escalate(incident, clock, now)
            if step is not None:
                escalations.append(step)

        auto_closed = self.__auto_close(now)
        self.__uow.commit()

        report = TickReport(tuple(warned), tuple(breached), tuple(escalations), tuple(auto_closed))
        if not report.did_nothing:
            logger.info(report.summary)
        self.__dispatch(report)
        return report

    # ------------------------------------------------------------ steps 1 and 2
    def __record(
        self, incident: Incident, clock: SLAClock, now: datetime, *, breach: bool
    ) -> list[SLAViolation]:
        """Write the warnings or the breaches this incident has newly earned."""
        found: list[SLAViolation] = []
        wanted = SLAStatus.BREACHED if breach else SLAStatus.AT_RISK
        pairs = (
            (
                ViolationKind.RESPONSE_BREACH if breach else ViolationKind.RESPONSE_WARNING,
                clock.response_status(now),
                clock.response_deadline,
            ),
            (
                ViolationKind.RESOLUTION_BREACH if breach else ViolationKind.RESOLUTION_WARNING,
                clock.resolution_status(now),
                clock.resolution_deadline_at_rest,
            ),
        )
        for kind, status, deadline in pairs:
            if status is not wanted:
                continue
            violation = SLAViolation(
                incident_id=incident.id,
                kind=kind,
                cycle=incident.reopen_count,
                deadline=deadline,
                detected_at=now,
            )
            if self.__uow.violations.record(violation):
                found.append(violation)
                self.__audit.record(
                    AuditAction.SLA_VIOLATED,
                    incident_id=incident.id,
                    details={"kind": kind.value, "deadline": deadline.isoformat()},
                )
        return found

    # ------------------------------------------------------------ step 3
    def __escalate(self, incident: Incident, clock: SLAClock, now: datetime) -> Escalation | None:
        """Ask the chain who should own this now, and hand it over if that is someone new.

        Only an incident that can still be reassigned is asked about: §4 has no ASSIGNED move
        out of RESOLVED or VERIFIED, so asking the chain about one would mean attempting an
        escalation that cannot happen and logging the failure on every tick for ever.
        """
        if incident.priority is None or not _can_be_escalated(incident):
            return None
        moment = now
        decision = decide_escalation(
            EscalationContext(
                priority=incident.priority,
                acknowledged=incident.acknowledged_at is not None,
                response_target=clock.target.response,
                elapsed=moment - clock.started_at,
                current_level=incident.escalation_level,
                resolution_breached=clock.resolution_status(moment) is SLAStatus.BREACHED,
            )
        )
        if decision is None or decision.level <= incident.escalation_level:
            return None

        found = self.__next_owner(decision.level, incident)
        if found is None:
            logger.warning(
                "nobody above level %s to escalate %s to; leaving it with user %s",
                incident.escalation_level,
                incident.id,
                incident.assignee_id,
            )
            return None
        level, owner = found
        decision = replace(decision, level=level)
        try:
            incident.escalate(owner.id, level, None, self.__clock)
        except ITSMError as error:  # pragma: no cover - _can_be_escalated rules this out
            logger.warning("could not escalate %s: %s", incident.id, error)
            return None

        self.__uow.incidents.save(incident)
        incident.pull_events()  # the audit entry below describes the escalation itself
        self.__audit.record(
            AuditAction.INCIDENT_ESCALATED,
            incident_id=incident.id,
            details={"level": decision.level, "reason": decision.reason, "to": owner.id},
        )
        return Escalation(incident.id, owner.id, decision.level, decision.reason)

    def __next_owner(self, wanted_level: int, incident: Incident) -> tuple[int, User] | None:
        """The first level at or above ``wanted_level`` that has somebody new to hand this to.

        §5.5's chain can ask for a level the current assignee already holds — a Team Lead
        carrying their own team's incident is the common case — and handing it back to the same
        person would leave the incident stuck while the monitor logged a failure every tick.
        So the search continues up the chain instead of stopping there.
        """
        for level in range(wanted_level, MAX_ESCALATION_LEVEL + 1):
            role = _ROLE_AT_LEVEL.get(level)
            if role is None:  # pragma: no cover - every level 1-3 has a role
                continue
            owner = self.__owner_for(role, incident)
            if owner is not None and owner.id != incident.assignee_id:
                return level, owner
        return None

    def __owner_for(self, role: Role, incident: Incident) -> User | None:
        """Who holds ``role`` for this incident: the team's lead (D-004), or any admin."""
        if role is Role.TEAM_LEAD:
            return self.__team_lead(incident)
        wanted = escalation_level(role)
        for candidate in self.__uow.users.administrators():
            if candidate.active and escalation_level(candidate.role) == wanted:
                return candidate
        return None

    def __team_lead(self, incident: Incident) -> User | None:
        if incident.assignee_id is not None:
            assignee = self.__user(incident.assignee_id)
            if isinstance(assignee, Technician) and assignee.team_id is not None:
                lead_id = self.__uow.catalogue.get_team(assignee.team_id).lead_id
                if lead_id is not None and lead_id != incident.assignee_id:
                    return self.__user(lead_id)
        lead_id = fallback_lead(self.__uow.catalogue.teams(), excluding=incident.assignee_id)
        return None if lead_id is None else self.__user(lead_id)

    def __user(self, user_id: int) -> User | None:
        try:
            return self.__uow.users.get(user_id)
        except ITSMError:
            return None

    # ------------------------------------------------------------ step 4
    def __auto_close(self, now: datetime) -> list[str]:
        """BR-03: close a resolution the reporter never answered, 72 hours later."""
        cutoff = now - AUTO_CLOSE_AFTER
        closed: list[str] = []
        for incident in self.__uow.incidents.awaiting_auto_close(cutoff):
            try:
                incident.auto_close(self.__clock)
            except ITSMError as error:  # pragma: no cover - the query only returns RESOLVED
                logger.warning("could not auto-close %s: %s", incident.id, error)
                continue
            self.__uow.incidents.save(incident)
            incident.pull_events()
            self.__audit.record(
                AuditAction.INCIDENT_STATE_CHANGED,
                incident_id=incident.id,
                details={"to": "CLOSED", "reason": "72 h without verification (BR-03)"},
            )
            closed.append(incident.id)
        return closed

    # ------------------------------------------------------------ afterwards (§5.4)
    def __dispatch(self, report: TickReport) -> None:
        """Notify after the commit, so a dead mail server cannot undo a recorded breach.

        All four §5.4 rows the monitor is responsible for go out here: the SLA warning and
        breach, the escalation (to its new owner) and the 72-hour auto-close (to the reporter).
        """
        if self.__notify is None:
            return
        for violation in report.warned:
            self.__send(
                NotificationEvent.SLA_APPROACHING, violation.incident_id, self.__detail(violation)
            )
        for violation in report.breached:
            self.__send(
                NotificationEvent.SLA_VIOLATED, violation.incident_id, self.__detail(violation)
            )
        for step in report.escalations:
            self.__send(
                NotificationEvent.ESCALATED,
                step.incident_id,
                f"Escalated to level {step.level}: {step.reason}.",
            )
        for incident_id in report.auto_closed:
            self.__send(
                NotificationEvent.CLOSED,
                incident_id,
                "Closed automatically after 72 hours without an answer (BR-03).",
            )

    def __send(self, event: NotificationEvent, incident_id: str, detail: str) -> None:
        if self.__notify is None:
            return
        try:
            self.__notify(event, self.__uow.incidents.get(incident_id), detail)
        except Exception:
            logger.exception("could not notify about %s on %s", event, incident_id)

    @staticmethod
    def __detail(violation: SLAViolation) -> str:
        which = "response" if violation.kind.is_response else "resolution"
        verb = "passed" if violation.kind.is_breach else "is close to"
        return f"The {which} deadline {verb} {violation.deadline.isoformat()}."


def _can_be_escalated(incident: Incident) -> bool:
    """True when §4 still allows this incident to be handed to someone else."""
    return incident.status in OPEN_STATUSES or incident.status in _CLASSIFIED_BUT_UNASSIGNED


#: An incident nobody has picked up yet can still be escalated to a lead (§5.5).
_CLASSIFIED_BUT_UNASSIGNED = frozenset({IncidentStatus.NEW, IncidentStatus.CLASSIFIED})

#: §5.5's chain by level: 1 Team Lead, 2 Administrator, 3 IT Manager.
_ROLE_AT_LEVEL: Mapping[int, Role] = MappingProxyType(
    {1: Role.TEAM_LEAD, 2: Role.ADMINISTRATOR, 3: Role.IT_MANAGER}
)


def ticks_per(interval: timedelta, clock: Clock) -> float:
    """How many real seconds one clock-time ``interval`` takes (D-003)."""
    return clock.real_seconds(interval)
