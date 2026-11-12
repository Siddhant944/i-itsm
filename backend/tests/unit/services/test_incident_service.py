"""The IncidentService facade (blueprint §2, §5, §7).

These run on the in-memory repositories and a FakeClock, so every rule is checked exactly:
who may act (BR-01, BR-02, BR-03), what reporting does end to end, the audit record written in
the same transaction (BR-10) and the notification that only goes out afterwards (§5.4).
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import FakeClock
from app.domain.audit import AuditAction, verify_chain
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.errors import (
    IncidentNotFoundError,
    InvalidIncidentError,
    InvalidStateTransitionError,
    InvalidUserInputError,
    ServiceNotFoundError,
    TechnicianUnavailableError,
    UnauthorizedOperationError,
)
from app.domain.events import DomainEvent, IncidentCreated, IncidentStateChanged
from app.domain.incident import CancelReason, NoteKind
from app.domain.permissions import Role
from app.domain.priority import Priority
from app.domain.rule_advisor import RuleBasedAdvisor
from app.domain.sla import default_policies
from app.domain.states import IncidentStatus as S
from app.domain.users import Technician, User, UserFactory
from app.domain.value_objects import SkillSet
from app.repositories.memory import InMemoryUnitOfWork
from app.services.dispatcher import PostCommitDispatcher
from app.services.incident_service import IncidentService

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
REPORTER, OTHER, TECH, TECH2, LEAD, ADMIN = 1, 2, 3, 4, 5, 6
WIFI, DATABASE = 1, 2
NETWORK, PAYMENTS = 1, 2


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def delivered() -> list[DomainEvent]:
    return []


@pytest.fixture
def uow() -> InMemoryUnitOfWork:
    unit = InMemoryUnitOfWork()
    unit.catalogue.save_skill(Skill(1, "networking"))
    unit.catalogue.save_skill(Skill(2, "web"))
    unit.catalogue.save_category(
        Category(NETWORK, "Network", required_skill_id=1, keywords=("wifi", "network"))
    )
    unit.catalogue.save_category(
        Category(
            PAYMENTS,
            "Payments",
            required_skill_id=2,
            keywords=("fee", "payment"),
            minimum_priority=Priority.P2,
        )
    )
    unit.catalogue.save_service(ITService(WIFI, "Campus Wi-Fi", criticality=2))
    unit.catalogue.save_service(ITService(DATABASE, "Fee Payment Portal", criticality=3))
    unit.catalogue.save_policies(default_policies())
    unit.catalogue.save_team(Team(1, "Network Operations"))

    unit.users.add(_user(Role.EMPLOYEE, REPORTER))
    unit.users.add(_user(Role.EMPLOYEE, OTHER))
    unit.users.add(_tech(Role.TECHNICIAN, TECH, {"networking", "web"}))
    unit.users.add(_tech(Role.TECHNICIAN, TECH2, {"networking"}))
    unit.users.add(_tech(Role.TEAM_LEAD, LEAD, {"networking"}))
    unit.users.add(_user(Role.ADMINISTRATOR, ADMIN))
    unit.catalogue.save_team(_team_with_members(unit))
    return unit


def _team_with_members(unit: InMemoryUnitOfWork) -> Team:
    team = unit.catalogue.get_team(1)
    for member in (TECH, TECH2, LEAD):
        team.add_member(member)
    team.set_lead(LEAD)
    return team


def _user(role: Role, user_id: int) -> User:
    return UserFactory.create(
        role, user_id=user_id, email=f"u{user_id}@campus.edu", full_name=f"User {user_id}"
    )


def _tech(role: Role, user_id: int, skills: set[str]) -> User:
    return UserFactory.create(
        role,
        user_id=user_id,
        email=f"u{user_id}@campus.edu",
        full_name=f"User {user_id}",
        skills=SkillSet(skills),
        experience_level=2,
        team_id=1,
    )


@pytest.fixture
def service(
    uow: InMemoryUnitOfWork, clock: FakeClock, delivered: list[DomainEvent]
) -> IncidentService:
    dispatcher = PostCommitDispatcher([delivered.append])
    return IncidentService(uow, clock, dispatcher=dispatcher, advisor=RuleBasedAdvisor())


def who(uow: InMemoryUnitOfWork, user_id: int) -> User:
    return uow.users.get(user_id)


def away(uow: InMemoryUnitOfWork, user_id: int) -> None:
    """Mark a technician unavailable, as an admin would."""
    technician = uow.users.get(user_id)
    assert isinstance(technician, Technician)
    technician.mark_unavailable()
    uow.users.save(technician)


def report(service: IncidentService, uow: InMemoryUnitOfWork, **overrides: object) -> str:
    fields: dict[str, object] = {
        "title": "Wi-Fi down in the library",
        "description": "No wifi signal on the first floor",
        "service_id": WIFI,
        "impact": 2,
        "urgency": 2,
    }
    fields.update(overrides)
    return service.report(who(uow, REPORTER), **fields).incident.id  # type: ignore[arg-type]


# ---------------------------------------------------------------- reporting
def test_reporting_classifies_prioritises_sets_the_sla_and_assigns(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    result = service.report(
        who(uow, REPORTER),
        title="Wi-Fi down in the library",
        description="No wifi signal on the first floor",
        service_id=WIFI,
        impact=2,
        urgency=2,
    )
    incident = result.incident

    assert incident.id == "INC-2026-0001"
    assert incident.category_id == NETWORK  # suggested by the keywords, applied and recorded
    assert result.suggestion is not None
    assert result.suggestion.source == "rules"
    assert result.suggestion.confidence > 0
    assert incident.priority is Priority.P3  # 2 x 2 x 2 = 8 -> P3
    assert incident.sla_clock is not None
    assert incident.sla_clock.target.response == timedelta(hours=2)  # silver, P3
    assert incident.status is S.ASSIGNED
    assert incident.assignee_id in (TECH, TECH2, LEAD)
    assert result.assignment is not None
    assert result.assignment.reasons


def test_a_confirmed_category_wins_over_the_suggestion(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    """The reporter or the UI may override the AI; nothing is applied silently (§6.1)."""
    result = service.report(
        who(uow, REPORTER),
        title="Wi-Fi down",
        description="No wifi at all",
        service_id=WIFI,
        impact=1,
        urgency=1,
        category_id=PAYMENTS,
    )
    assert result.incident.category_id == PAYMENTS
    assert result.suggestion is None


def test_the_category_floor_raises_the_priority(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    """BR-05: Payments has a P2 floor, so a trivial-looking report still gets P2."""
    result = service.report(
        who(uow, REPORTER),
        title="Fee payment failed",
        description="The payment did not go through",
        service_id=DATABASE,
        impact=1,
        urgency=1,
        category_id=PAYMENTS,
    )
    assert result.incident.priority is Priority.P2


def test_reporting_is_refused_for_a_retired_or_unknown_service(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    retired = uow.catalogue.get_service(WIFI)
    retired.retire()
    uow.catalogue.save_service(retired)
    with pytest.raises(ServiceNotFoundError):
        report(service, uow)
    with pytest.raises(ServiceNotFoundError):
        report(service, uow, service_id=999)


def test_reporting_validates_its_input(service: IncidentService, uow: InMemoryUnitOfWork) -> None:
    with pytest.raises(InvalidUserInputError):
        report(service, uow, title="   ")
    with pytest.raises(InvalidUserInputError):
        report(service, uow, impact=4)


def test_a_technician_may_also_report(service: IncidentService, uow: InMemoryUnitOfWork) -> None:
    result = service.report(
        who(uow, TECH),
        title="My own laptop will not charge",
        description="The dock does nothing",
        service_id=WIFI,
        impact=1,
        urgency=1,
    )
    assert result.incident.reporter_id == TECH
    assert result.needs_triage is True


def test_an_unclassifiable_report_waits_for_a_human(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    """§4 runs NEW -> CLASSIFIED -> ASSIGNED, so an incident nobody could classify stays NEW."""
    result = service.report(
        who(uow, REPORTER),
        title="Something is odd",
        description="I cannot describe it any better than that",
        service_id=WIFI,
        impact=1,
        urgency=1,
    )
    assert result.needs_triage is True
    assert result.suggestion is not None
    assert result.suggestion.category_id is None
    assert result.incident.status is S.NEW
    assert result.incident.assignee_id is None
    assert result.incident.priority is Priority.P4  # still prioritised and SLA-tracked
    assert result.incident.sla_clock is not None

    triaged = service.override_category(who(uow, ADMIN), result.incident.id, NETWORK)
    assert triaged.status is S.CLASSIFIED
    assert triaged.category_id == NETWORK


def test_when_nobody_has_capacity_the_incident_is_queued_for_the_team_lead(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    """Blueprint §8: an automatic assignment with nobody free is queued, not an error."""
    for technician_id in (TECH, TECH2, LEAD):
        away(uow, technician_id)

    result = service.report(
        who(uow, REPORTER),
        title="Wi-Fi down",
        description="No wifi signal",
        service_id=WIFI,
        impact=2,
        urgency=2,
    )
    assert result.queued_for_team_lead is True
    assert result.assignment is None
    assert result.incident.assignee_id is None
    assert result.incident.status is S.CLASSIFIED


def test_an_incident_queued_for_the_team_lead_can_be_seen_and_assigned_by_one(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    """P3 review: with no assignee it matched no team, so no lead could open or assign it."""
    for technician_id in (TECH, TECH2, LEAD):
        away(uow, technician_id)
    queued = report(service, uow)

    assert service.get(who(uow, LEAD), queued).assignee_id is None
    with pytest.raises(UnauthorizedOperationError):
        service.get(who(uow, TECH), queued)
    with pytest.raises(UnauthorizedOperationError):
        service.get(who(uow, OTHER), queued)

    back = uow.users.get(TECH)
    assert isinstance(back, Technician)
    back.mark_available()
    uow.users.save(back)
    assigned = service.reassign(who(uow, LEAD), queued, TECH)
    assert assigned.assignee_id == TECH
    assert assigned.status is S.ASSIGNED


def test_an_incident_on_a_since_retired_service_can_still_be_worked(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    """P3 review: retiring a service made every further step on its incidents a 404."""
    incident_id = report(service, uow)
    wifi = uow.catalogue.get_service(WIFI)
    wifi.retire()
    uow.catalogue.save_service(wifi)

    assert service.assignment_advice(service.get(who(uow, ADMIN), incident_id)).ranked
    overridden = service.override_priority(who(uow, ADMIN), incident_id, Priority.P1, "Exam week")
    assert overridden.priority is Priority.P1
    with pytest.raises(ServiceNotFoundError):
        report(service, uow)


def test_a_retired_category_is_refused_for_a_new_choice(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    payments = uow.catalogue.get_category(PAYMENTS)
    payments.retire()
    uow.catalogue.save_category(payments)
    with pytest.raises(InvalidUserInputError):
        report(service, uow, category_id=PAYMENTS)
    with pytest.raises(InvalidUserInputError):
        service.override_category(who(uow, ADMIN), incident_id, PAYMENTS)


# ---------------------------------------------------------------- BR-01, BR-02
def test_BR01_an_employee_cannot_read_another_persons_incident(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    assert service.get(who(uow, REPORTER), incident_id).id == incident_id
    assert service.get(who(uow, ADMIN), incident_id).id == incident_id
    with pytest.raises(UnauthorizedOperationError):
        service.get(who(uow, OTHER), incident_id)


def test_BR01_my_incidents_lists_only_my_own(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    mine = report(service, uow)
    service.report(
        who(uow, OTHER),
        title="Printer jam",
        description="The printer jams every page",
        service_id=WIFI,
        impact=1,
        urgency=1,
    )
    assert [i.id for i in service.my_incidents(who(uow, REPORTER))] == [mine]
    assert len(service.my_incidents(who(uow, OTHER))) == 1


def test_BR02_only_the_assignee_the_lead_or_an_admin_may_acknowledge(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    assignee = service.get(who(uow, ADMIN), incident_id).assignee_id
    assert assignee is not None
    stranger = next(t for t in (TECH, TECH2, LEAD) if t != assignee)

    with pytest.raises(UnauthorizedOperationError):
        service.acknowledge(who(uow, REPORTER), incident_id)
    if stranger != LEAD:
        with pytest.raises(UnauthorizedOperationError):
            service.acknowledge(who(uow, stranger), incident_id)
    assert service.acknowledge(who(uow, assignee), incident_id).status is S.ACKNOWLEDGED


def test_BR02_a_team_lead_may_act_on_their_teams_incident(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    assert service.acknowledge(who(uow, LEAD), incident_id).status is S.ACKNOWLEDGED


def test_a_technician_queue_needs_the_permission(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    assignee = service.get(who(uow, ADMIN), incident_id).assignee_id
    assert assignee is not None
    assert [i.id for i in service.my_queue(who(uow, assignee))] == [incident_id]
    with pytest.raises(UnauthorizedOperationError):
        service.my_queue(who(uow, REPORTER))


# ---------------------------------------------------------------- the working lifecycle
def test_the_whole_lifecycle_through_the_facade(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    incident_id = report(service, uow)
    assignee = service.get(who(uow, ADMIN), incident_id).assignee_id
    assert assignee is not None
    technician, reporter = who(uow, assignee), who(uow, REPORTER)

    clock.advance(timedelta(minutes=5))
    service.acknowledge(technician, incident_id)
    service.start(technician, incident_id)
    service.add_note(technician, incident_id, "Rebooted the access point")
    service.request_information(technician, incident_id, "Which floor are you on?")
    assert service.get(reporter, incident_id).status is S.ON_HOLD

    clock.advance(timedelta(hours=1))
    assert service.provide_information(reporter, incident_id, "First floor").status is S.IN_PROGRESS
    resolved = service.resolve(technician, incident_id, "Replaced the access point")
    assert resolved.status is S.RESOLVED
    assert resolved.resolution is not None

    verified = service.verify(reporter, incident_id, rating=5, comment="Quick work")
    assert verified.status is S.VERIFIED
    assert verified.feedback is not None
    assert service.close(technician, incident_id).status is S.CLOSED

    stored = service.get(reporter, incident_id)
    assert [note.kind for note in stored.notes] == [
        NoteKind.NOTE,
        NoteKind.INFO_REQUEST,
        NoteKind.INFO_RESPONSE,
    ]
    assert stored.sla_clock is not None
    assert stored.sla_clock.paused_accumulated == timedelta(hours=1)


def test_an_illegal_move_is_refused_by_the_state_machine(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    assignee = service.get(who(uow, ADMIN), incident_id).assignee_id
    assert assignee is not None
    with pytest.raises(InvalidStateTransitionError):
        service.resolve(who(uow, assignee), incident_id, "Too early")


def test_BR04_resolving_needs_a_summary(service: IncidentService, uow: InMemoryUnitOfWork) -> None:
    incident_id = report(service, uow)
    assignee = service.get(who(uow, ADMIN), incident_id).assignee_id
    assert assignee is not None
    technician = who(uow, assignee)
    service.acknowledge(technician, incident_id)
    service.start(technician, incident_id)
    with pytest.raises(InvalidIncidentError):
        service.resolve(technician, incident_id, "   ")
    assert service.get(technician, incident_id).status is S.IN_PROGRESS


def test_BR03_only_the_reporter_verifies_or_rejects(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    assignee = service.get(who(uow, ADMIN), incident_id).assignee_id
    assert assignee is not None
    technician = who(uow, assignee)
    service.acknowledge(technician, incident_id)
    service.start(technician, incident_id)
    service.resolve(technician, incident_id, "Replaced the access point")

    for actor_id in (assignee, ADMIN, OTHER):
        with pytest.raises(UnauthorizedOperationError):
            service.verify(who(uow, actor_id), incident_id, rating=5)
        with pytest.raises(UnauthorizedOperationError):
            service.reject(who(uow, actor_id), incident_id, reason="not fixed")

    rejected = service.reject(who(uow, REPORTER), incident_id, reason="It came back")
    assert rejected.status is S.IN_PROGRESS
    assert rejected.resolution is None
    assert rejected.reopen_count == 1


def test_cancelling_a_duplicate_needs_a_real_parent(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    first = report(service, uow)
    second = report(service, uow, title="Projector is dim", description="Hall F-105, yellow")
    with pytest.raises(IncidentNotFoundError):
        service.cancel(
            who(uow, ADMIN), second, CancelReason.DUPLICATE, duplicate_of="INC-2026-9999"
        )
    cancelled = service.cancel(who(uow, ADMIN), second, CancelReason.DUPLICATE, duplicate_of=first)
    assert cancelled.status is S.CANCELLED
    assert cancelled.parent_id == first


def test_only_the_reporter_or_an_admin_cancels(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    with pytest.raises(UnauthorizedOperationError):
        service.cancel(who(uow, OTHER), incident_id)
    assert service.cancel(who(uow, REPORTER), incident_id).status is S.CANCELLED


# ---------------------------------------------------------------- overrides and reassignment
def test_BR05_a_priority_override_retargets_the_sla_and_is_audited(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    overridden = service.override_priority(
        who(uow, ADMIN), incident_id, Priority.P1, reason="Exam tomorrow"
    )
    assert overridden.priority is Priority.P1
    assert overridden.priority_overridden is True
    assert overridden.sla_clock is not None
    assert overridden.sla_clock.target.response == timedelta(minutes=10)  # silver, P1

    reasons = [
        record.details.get("reason")
        for record in uow.audit.records(limit=100)
        if record.action is AuditAction.PRIORITY_OVERRIDDEN
    ]
    assert "Exam tomorrow" in reasons


def test_BR05_an_override_without_a_reason_is_refused(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    with pytest.raises(InvalidUserInputError):
        service.override_priority(who(uow, ADMIN), incident_id, Priority.P1, reason="  ")
    assert service.get(who(uow, ADMIN), incident_id).priority_overridden is False


def test_an_employee_cannot_override_anything(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    with pytest.raises(UnauthorizedOperationError):
        service.override_priority(who(uow, REPORTER), incident_id, Priority.P1, reason="mine")
    with pytest.raises(UnauthorizedOperationError):
        service.override_category(who(uow, REPORTER), incident_id, PAYMENTS)
    with pytest.raises(UnauthorizedOperationError):
        service.reassign(who(uow, REPORTER), incident_id, TECH2)


def test_overriding_the_category_keeps_the_status_and_is_recorded(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    """Correcting a category is not a lifecycle step, so an assigned incident stays assigned."""
    incident_id = report(service, uow)
    corrected = service.override_category(who(uow, ADMIN), incident_id, PAYMENTS)
    assert corrected.category_id == PAYMENTS
    assert corrected.status is S.ASSIGNED
    actions = [r.action for r in uow.audit.records(limit=100, incident_id=incident_id)]
    assert AuditAction.CATEGORY_OVERRIDDEN in actions


def test_BR06_reassignment_refuses_an_unavailable_technician(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    away(uow, TECH2)
    with pytest.raises(TechnicianUnavailableError):
        service.reassign(who(uow, LEAD), incident_id, TECH2)


def test_reassignment_refuses_someone_who_is_not_a_technician(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    with pytest.raises(InvalidUserInputError):
        service.reassign(who(uow, ADMIN), incident_id, OTHER)


def test_reassignment_moves_the_incident(service: IncidentService, uow: InMemoryUnitOfWork) -> None:
    incident_id = report(service, uow)
    moved = service.reassign(who(uow, ADMIN), incident_id, TECH2)
    assert moved.assignee_id == TECH2
    assert moved.status is S.ASSIGNED


def test_assignment_advice_ranks_with_reasons(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident = service.get(who(uow, ADMIN), report(service, uow))
    advice = service.assignment_advice(incident)
    assert advice.strategy == "smart"
    assert len(advice.ranked) >= 2
    assert advice.ranked[0].score >= advice.ranked[-1].score
    assert all(score.reasons for score in advice.ranked)


# ---------------------------------------------------------------- audit and notifications
def test_BR10_every_change_is_audited_in_one_unbroken_chain(
    service: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report(service, uow)
    assignee = service.get(who(uow, ADMIN), incident_id).assignee_id
    assert assignee is not None
    service.acknowledge(who(uow, assignee), incident_id)
    service.add_note(who(uow, assignee), incident_id, "Looking into it")

    records = uow.audit.records(limit=100, incident_id=incident_id)
    actions = [record.action for record in records]
    assert AuditAction.INCIDENT_CREATED in actions
    assert AuditAction.INCIDENT_STATE_CHANGED in actions
    assert AuditAction.INCIDENT_NOTE_ADDED in actions
    assert verify_chain(uow.audit.records(limit=100)).intact is True


def test_notifications_are_delivered_only_after_the_commit(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """§5.4: the audit record is in the transaction; the notification goes out after it."""
    seen: list[tuple[str, int]] = []

    def subscriber(event: DomainEvent) -> None:
        # By the time a subscriber runs, the change is committed and readable.
        seen.append((type(event).__name__, uow.committed))

    service = IncidentService(
        uow, clock, dispatcher=PostCommitDispatcher([subscriber]), advisor=RuleBasedAdvisor()
    )
    report(service, uow)
    names = [name for name, _ in seen]
    assert names[0] == IncidentCreated.__name__
    assert all(committed > 0 for _, committed in seen)
    assert IncidentStateChanged.__name__ in names


def test_a_failing_notification_does_not_undo_the_change(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    def explode(_: DomainEvent) -> None:
        raise RuntimeError("the mail server is down")

    service = IncidentService(
        uow, clock, dispatcher=PostCommitDispatcher([explode]), advisor=RuleBasedAdvisor()
    )
    incident_id = report(service, uow)
    assert uow.incidents.get(incident_id).status is S.ASSIGNED


def test_a_refused_change_notifies_nobody(
    service: IncidentService, uow: InMemoryUnitOfWork, delivered: list[DomainEvent]
) -> None:
    incident_id = report(service, uow)
    delivered.clear()
    with pytest.raises(UnauthorizedOperationError):
        service.acknowledge(who(uow, REPORTER), incident_id)
    assert delivered == []


def test_reporting_without_an_advisor_still_works(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """§6: with the AI off, the system degrades to no suggestion, not to an error."""
    service = IncidentService(uow, clock)
    result = service.report(
        who(uow, REPORTER),
        title="Wi-Fi down",
        description="No wifi signal",
        service_id=WIFI,
        impact=2,
        urgency=2,
    )
    assert result.suggestion is None
    assert result.incident.category_id is None
    assert result.needs_triage is True
    assert result.incident.status is S.NEW
