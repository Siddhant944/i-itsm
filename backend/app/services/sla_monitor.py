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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.clock import Clock
from app.domain.audit import AuditAction
from app.domain.errors import ITSMError
from app.domain.escalation import EscalationContext, decide_escalation
from app.domain.incident import Incident
from app.domain.notifications import NotificationEvent
from app.domain.permissions import Role, escalation_level
from app.domain.repositories import UnitOfWork
from app.domain.sla import SLAClock, SLAStatus, SLAViolation, ViolationKind
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
class TickReport:
    """What one tick did, so a test or the demo can see it rather than infer it."""

    warned: tuple[SLAViolation, ...] = field(default_factory=tuple)
    breached: tuple[SLAViolation, ...] = field(default_factory=tuple)
    escalated: tuple[str, ...] = field(default_factory=tuple)
    auto_closed: tuple[str, ...] = field(default_factory=tuple)

    @property
    def did_nothing(self) -> bool:
        return not (self.warned or self.breached or self.escalated or self.auto_closed)

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
        escalated: list[str] = []

        for incident in self.__uow.incidents.needing_sla_attention(now):
            clock = incident.sla_clock
            if clock is None:  # pragma: no cover - the query only returns incidents with one
                continue
            warned.extend(self.__record(incident, clock, now, breach=False))
            breached.extend(self.__record(incident, clock, now, breach=True))
            if self.__escalate(incident, clock, now):
                escalated.append(incident.id)

        auto_closed = self.__auto_close(now)
        self.__uow.commit()

        report = TickReport(tuple(warned), tuple(breached), tuple(escalated), tuple(auto_closed))
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
    def __escalate(self, incident: Incident, clock: SLAClock, now: datetime) -> bool:
        """Ask the chain who should own this now, and hand it over if that is someone new."""
        if incident.priority is None:
            return False
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
            return False

        owner = self.__owner_for(decision.target_role, incident)
        if owner is None:
            logger.warning(
                "no %s to escalate %s to; leaving it at level %s",
                decision.target_role.value,
                incident.id,
                incident.escalation_level,
            )
            return False
        try:
            incident.escalate(owner.id, decision.level, None, self.__clock)
        except ITSMError as error:
            logger.warning("could not escalate %s: %s", incident.id, error)
            return False

        self.__uow.incidents.save(incident)
        incident.pull_events()  # the audit entry below describes the escalation itself
        self.__audit.record(
            AuditAction.INCIDENT_ESCALATED,
            incident_id=incident.id,
            details={"level": decision.level, "reason": decision.reason, "to": owner.id},
        )
        return True

    def __owner_for(self, role: Role, incident: Incident) -> User | None:
        """Who holds ``role`` for this incident: the team's lead (D-004), or any admin."""
        if role is Role.TEAM_LEAD:
            return self.__team_lead(incident)
        if role is Role.TECHNICIAN:
            return None if incident.assignee_id is None else self.__user(incident.assignee_id)
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
        for team in self.__uow.catalogue.teams():
            if team.lead_id is not None and team.lead_id != incident.assignee_id:
                return self.__user(team.lead_id)
        return None

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
        """Notify after the commit, so a dead mail server cannot undo a recorded breach."""
        if self.__notify is None:
            return
        for violation in report.warned:
            self.__send(NotificationEvent.SLA_APPROACHING, violation)
        for violation in report.breached:
            self.__send(NotificationEvent.SLA_VIOLATED, violation)

    def __send(self, event: NotificationEvent, violation: SLAViolation) -> None:
        if self.__notify is None:
            return
        try:
            incident = self.__uow.incidents.get(violation.incident_id)
            self.__notify(event, incident, self.__detail(violation))
        except Exception:
            logger.exception("could not notify about %s on %s", event, violation.incident_id)

    @staticmethod
    def __detail(violation: SLAViolation) -> str:
        which = "response" if violation.kind.is_response else "resolution"
        verb = "passed" if violation.kind.is_breach else "is close to"
        return f"The {which} deadline {verb} {violation.deadline.isoformat()}."


def ticks_per(interval: timedelta, clock: Clock) -> float:
    """How many real seconds one clock-time ``interval`` takes (D-003)."""
    return clock.real_seconds(interval)
