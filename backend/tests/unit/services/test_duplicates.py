"""Duplicate detection through the facade (blueprint §6.2, BR-09).

In-memory repositories, a FakeClock and the offline TF-IDF provider, so every score is
reproducible. The fake providers at the bottom stand in for Gemini: one stable, one down.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import FakeClock
from app.domain.audit import AuditAction
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.errors import (
    DuplicateIncidentError,
    InvalidUserInputError,
    NetworkFailureError,
    UnauthorizedOperationError,
)
from app.domain.incident import CancelReason
from app.domain.notifications import ChannelName, NotificationEvent
from app.domain.permissions import Role
from app.domain.ports import EmbeddingProvider
from app.domain.rule_advisor import RuleBasedAdvisor
from app.domain.similarity import TfIdfEmbeddings
from app.domain.sla import default_policies
from app.domain.states import IncidentStatus as S
from app.domain.users import User, UserFactory
from app.domain.value_objects import SkillSet
from app.repositories.memory import InMemoryUnitOfWork
from app.services.dispatcher import PostCommitDispatcher
from app.services.duplicates import DuplicateDetector
from app.services.incident_service import IncidentService, ReportedIncident
from app.services.notifications.service import NotificationService

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
ASHA, BILAL, CHITRA, TECH, TECH2, LEAD, ADMIN = 1, 2, 3, 4, 5, 6, 7
FEES, WIFI = 1, 2

#: Unrelated reports, so the corpus looks like a helpdesk rather than three payment tickets.
BACKGROUND = (
    ("Projector will not switch on", "Lecture hall F-105 before the ten o'clock class", WIFI),
    ("Printer jammed", "Paper stuck in tray two of the admin office printer", WIFI),
    ("Cannot open my mailbox", "Outlook asks for a password again and again", WIFI),
    ("Lab computer shows a black screen", "Machine fourteen in C-309 never boots", WIFI),
    ("Wi-Fi slow in the hostel", "Pages take a minute to load in H-block", WIFI),
    ("Fee receipt has the wrong name", "The receipt for the mess bill is misspelt", FEES),
)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def uow() -> InMemoryUnitOfWork:
    unit = InMemoryUnitOfWork()
    unit.catalogue.save_skill(Skill(1, "web"))
    unit.catalogue.save_category(
        Category(
            1,
            "Application",
            required_skill_id=1,
            keywords=("payment", "fee", "portal", "wifi", "printer", "projector", "mailbox", "lab"),
        )
    )
    unit.catalogue.save_service(ITService(FEES, "Fee Payment Portal", criticality=3))
    unit.catalogue.save_service(ITService(WIFI, "Campus Wi-Fi", criticality=1))
    unit.catalogue.save_policies(default_policies())
    for user_id in (ASHA, BILAL, CHITRA):
        unit.users.add(_user(Role.EMPLOYEE, user_id))
    for user_id, role in (
        (TECH, Role.TECHNICIAN),
        (TECH2, Role.TECHNICIAN),
        (LEAD, Role.TEAM_LEAD),
    ):
        unit.users.add(
            _user(role, user_id, skills=SkillSet({"web"}), experience_level=2, team_id=1)
        )
    unit.users.add(_user(Role.ADMINISTRATOR, ADMIN))
    team = Team(1, "Applications")
    for member in (TECH, TECH2, LEAD):
        team.add_member(member)
    team.set_lead(LEAD)
    unit.catalogue.save_team(team)
    return unit


def _user(role: Role, user_id: int, **extra: object) -> User:
    return UserFactory.create(
        role,
        user_id=user_id,
        email=f"u{user_id}@campus.edu",
        full_name=f"User {user_id}",
        **extra,  # type: ignore[arg-type]
    )


def make_service(
    uow: InMemoryUnitOfWork, clock: FakeClock, provider: EmbeddingProvider | None = None
) -> IncidentService:
    notifications = NotificationService(uow, clock)
    return IncidentService(
        uow,
        clock,
        dispatcher=PostCommitDispatcher([notifications.on_event]),
        advisor=RuleBasedAdvisor(),
        duplicates=DuplicateDetector(uow, clock, provider),
    )


@pytest.fixture
def service(uow: InMemoryUnitOfWork, clock: FakeClock) -> IncidentService:
    built = make_service(uow, clock)
    for title, description, service_id in BACKGROUND:
        report(built, uow, CHITRA, title, description, service_id=service_id)
    clock.advance(timedelta(hours=3))
    return built


def who(uow: InMemoryUnitOfWork, user_id: int) -> User:
    return uow.users.get(user_id)


def report(
    service: IncidentService,
    uow: InMemoryUnitOfWork,
    reporter: int,
    title: str,
    description: str = "",
    *,
    service_id: int = FEES,
    follow: str | None = None,
) -> ReportedIncident:
    return service.report(
        who(uow, reporter),
        title=title,
        description=description or title,
        service_id=service_id,
        impact=2,
        urgency=2,
        follow=follow,
    )


def ids(found: Sequence[object]) -> list[str]:
    return [candidate.incident.id for candidate in found]  # type: ignore[attr-defined]


# ------------------------------------------------------------------ suggesting
def test_BR09_the_briefs_three_payment_tickets_are_linked_as_possible_duplicates(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """INC101-INC103 share one word; the hybrid score still puts them together (§6.2)."""
    inc101 = report(service, uow, ASHA, "Payment application unavailable")
    clock.advance(5 * MIN)
    inc102 = report(service, uow, BILAL, "Payment transaction failing")
    clock.advance(5 * MIN)
    inc103 = report(service, uow, CHITRA, "Unable to make payment")

    assert inc101.possible_duplicates == ()
    assert ids(inc102.possible_duplicates) == [inc101.incident.id]
    assert set(ids(inc103.possible_duplicates)) == {inc101.incident.id, inc102.incident.id}
    # Suggested, not applied: all three are still live until a technician confirms.
    assert {r.incident.status for r in (inc101, inc102, inc103)} == {S.ASSIGNED}


def test_BR09_the_form_is_told_about_a_similar_open_incident_while_typing(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    existing = report(service, uow, ASHA, "Fee portal down", "The fee payment portal will not load")
    clock.advance(10 * MIN)

    check = service.similar_incidents(
        who(uow, BILAL), title="Fee payment portal not loading", description="", service_id=FEES
    )
    assert ids(check.candidates) == [existing.incident.id]
    assert check.provider == "tfidf"
    assert "same service" in check.best.score.reasons  # type: ignore[union-attr]

    nothing = service.similar_incidents(
        who(uow, BILAL), title="Need a new keyboard", description="", service_id=WIFI
    )
    assert nothing.candidates == ()


def test_BR09_a_closed_or_cancelled_incident_is_never_suggested(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    existing = report(service, uow, ASHA, "Fee portal down", "The fee payment portal will not load")
    service.cancel(who(uow, ASHA), existing.incident.id)
    clock.advance(40 * MIN)
    again = report(service, uow, ASHA, "Fee portal down", "The fee payment portal will not load")
    assert again.possible_duplicates == ()


def test_BR09_every_suggestion_is_audited_with_its_scores(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    first = report(service, uow, ASHA, "Fee portal down", "The fee payment portal will not load")
    clock.advance(MIN)
    second = report(service, uow, BILAL, "Fee portal is down", "Fee payment portal does not load")
    records = [
        record
        for record in uow.audit.records(incident_id=second.incident.id)
        if record.action is AuditAction.DUPLICATE_SUGGESTED
    ]
    assert len(records) == 1
    assert records[0].details["provider"] == "tfidf"
    assert records[0].details["candidates"][0]["id"] == first.incident.id  # type: ignore[index]


# ------------------------------------------------------------------ refusing a repeat (409)
def test_BR09_the_same_reporters_near_identical_report_within_30_minutes_is_refused(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    first = report(service, uow, ASHA, "Fee portal down", "The fee payment portal shows error 503")
    clock.advance(10 * MIN)
    with pytest.raises(DuplicateIncidentError) as refused:
        report(service, uow, ASHA, "Fee portal down", "The fee payment portal shows error 503!")
    assert refused.value.details["existing_incident_id"] == first.incident.id
    assert len(uow.incidents.list_by_reporter(ASHA)) == 1  # nothing was created


def test_BR09_someone_elses_identical_report_is_accepted_and_only_suggested(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    first = report(service, uow, ASHA, "Fee portal down", "The fee payment portal shows error 503")
    clock.advance(10 * MIN)
    second = report(
        service, uow, BILAL, "Fee portal down", "The fee payment portal shows error 503"
    )
    assert ids(second.possible_duplicates) == [first.incident.id]


def test_BR09_after_30_minutes_the_same_report_is_accepted_again(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    first = report(service, uow, ASHA, "Fee portal down", "The fee payment portal shows error 503")
    clock.advance(30 * MIN + timedelta(seconds=1))
    second = report(service, uow, ASHA, "Fee portal down", "The fee payment portal shows error 503")
    assert second.incident.id != first.incident.id
    assert ids(second.possible_duplicates) == [first.incident.id]


def test_BR09_a_different_problem_from_the_same_reporter_is_not_refused(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    report(service, uow, ASHA, "Fee portal down", "The fee payment portal shows error 503")
    clock.advance(MIN)
    other = report(service, uow, ASHA, "Fee receipt missing", "No receipt came for my hostel fees")
    assert other.incident.status is S.ASSIGNED


# ------------------------------------------------------------------ following instead
def test_BR09_following_a_suggestion_links_the_report_and_subscribes_the_reporter(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    parent = report(service, uow, ASHA, "Fee portal down", "The fee payment portal will not load")
    clock.advance(5 * MIN)
    followed = report(
        service,
        uow,
        BILAL,
        "Fee payment portal not loading",
        "Cannot load the fee portal",
        follow=parent.incident.id,
    )
    assert followed.incident.status is S.CANCELLED
    assert followed.incident.cancel_reason is CancelReason.DUPLICATE
    assert followed.incident.parent_id == parent.incident.id
    assert followed.followed is not None
    assert followed.incident.assignee_id is None  # nobody is given a second copy to work
    assert [i.id for i in uow.incidents.duplicates_of(parent.incident.id)] == [followed.incident.id]

    # D-005: the link is the subscription. Bilal hears when Asha's incident is fixed.
    service.acknowledge(who(uow, parent.incident.assignee_id or 0), parent.incident.id)
    service.start(who(uow, parent.incident.assignee_id or 0), parent.incident.id)
    service.resolve(
        who(uow, parent.incident.assignee_id or 0), parent.incident.id, "Restarted the gateway"
    )
    heard = [
        n
        for n in uow.notifications.in_app_for(BILAL)
        if n.event is NotificationEvent.RESOLVED and n.channel is ChannelName.IN_APP
    ]
    assert len(heard) == 1
    assert parent.incident.id in heard[0].subject
    assert "Restarted the gateway" in heard[0].body
    assert heard[0].incident_id == followed.incident.id  # filed under the one Bilal may open


def test_BR01_only_an_incident_the_check_suggested_can_be_followed(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """Following is a read path into someone else's incident, so it cannot be any id."""
    unrelated = report(service, uow, ASHA, "Need a new keyboard", "Keys are stuck", service_id=WIFI)
    clock.advance(MIN)
    with pytest.raises(InvalidUserInputError):
        report(service, uow, BILAL, "Fee portal down", follow=unrelated.incident.id)
    assert uow.incidents.list_by_reporter(BILAL) == ()


# ------------------------------------------------------------------ the technician confirms
def _two_alike(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> tuple[ReportedIncident, ReportedIncident]:
    parent = report(service, uow, ASHA, "Fee portal down", "The fee payment portal will not load")
    clock.advance(5 * MIN)
    child = report(service, uow, BILAL, "Fee payment portal not loading", "Cannot pay my fees")
    return parent, child


def test_BR09_the_technician_sees_the_possible_duplicate_and_confirms_it(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    parent, child = _two_alike(service, uow, clock)
    assignee = who(uow, child.incident.assignee_id or 0)

    seen = service.possible_duplicates(assignee, child.incident.id)
    assert ids(seen.candidates) == [parent.incident.id]

    confirmed = service.confirm_duplicate(assignee, child.incident.id, parent.incident.id)
    assert confirmed.status is S.CANCELLED
    assert confirmed.cancel_reason is CancelReason.DUPLICATE
    assert confirmed.parent_id == parent.incident.id
    assert service.duplicate_links(confirmed)[0] is not None
    assert service.duplicate_links(uow.incidents.get(parent.incident.id)) == (None, 1)

    told = [n for n in uow.notifications.in_app_for(BILAL) if parent.incident.id in n.subject]
    assert len(told) == 1
    assert "nothing more you need to do" in told[0].body
    # A cancelled incident has no duplicates to offer any more.
    assert service.possible_duplicates(assignee, child.incident.id).candidates == ()


def test_BR02_only_someone_who_may_work_the_incident_confirms_a_duplicate(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    parent, child = _two_alike(service, uow, clock)
    stranger = TECH2 if child.incident.assignee_id == TECH else TECH
    with pytest.raises(UnauthorizedOperationError):
        service.confirm_duplicate(who(uow, stranger), child.incident.id, parent.incident.id)
    with pytest.raises(UnauthorizedOperationError):
        service.confirm_duplicate(who(uow, BILAL), child.incident.id, parent.incident.id)
    with pytest.raises(UnauthorizedOperationError):
        service.possible_duplicates(who(uow, BILAL), child.incident.id)
    assert uow.incidents.get(child.incident.id).status is S.ASSIGNED
    assert service.confirm_duplicate(who(uow, ADMIN), child.incident.id, parent.incident.id)


def test_BR09_a_duplicate_needs_a_parent_that_is_open_and_is_not_itself_a_duplicate(
    service: IncidentService, uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    parent, child = _two_alike(service, uow, clock)
    clock.advance(5 * MIN)
    third = report(service, uow, CHITRA, "Fees page broken", "The fee payment portal is down")
    admin = who(uow, ADMIN)

    with pytest.raises(InvalidUserInputError):  # itself
        service.confirm_duplicate(admin, child.incident.id, child.incident.id)

    service.confirm_duplicate(admin, child.incident.id, parent.incident.id)
    with pytest.raises(InvalidUserInputError) as chained:  # a duplicate of a duplicate
        service.confirm_duplicate(admin, third.incident.id, child.incident.id)
    assert parent.incident.id in str(chained.value.details)

    with pytest.raises(InvalidUserInputError):  # the parent of others cannot become a child
        service.confirm_duplicate(admin, parent.incident.id, third.incident.id)

    withdrawn = report(service, uow, ASHA, "Need a new keyboard", "Keys stuck", service_id=WIFI)
    service.cancel(who(uow, ASHA), withdrawn.incident.id)
    with pytest.raises(InvalidUserInputError):  # a cancelled parent
        service.confirm_duplicate(admin, third.incident.id, withdrawn.incident.id)
    assert uow.incidents.get(third.incident.id).status is S.ASSIGNED


# ------------------------------------------------------------------ providers
class StableFake(EmbeddingProvider):
    """Stands in for Gemini: one fixed vector per text, and a count of what it was asked."""

    name = "fake-gemini"
    model = "fake-1"
    stable = True

    def __init__(self) -> None:
        self.asked: list[str] = []

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        self.asked.extend(texts)
        return [
            (1.0, 0.0) if "fee" in text.lower() or "pay" in text.lower() else (0.0, 1.0)
            for text in texts
        ]


class Unreachable(EmbeddingProvider):
    name = "down"
    model = "down-1"
    stable = True

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        raise NetworkFailureError


def test_BR09_a_stable_providers_vectors_are_stored_once_and_reused(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    provider = StableFake()
    service = make_service(uow, clock, provider)
    first = report(service, uow, ASHA, "Fee portal down")
    clock.advance(5 * MIN)
    second = report(service, uow, BILAL, "Cannot pay")
    assert ids(second.possible_duplicates) == [first.incident.id]

    stored = uow.embeddings.get_many(
        [first.incident.id, second.incident.id], provider="fake-gemini", model="fake-1"
    )
    assert stored == {first.incident.id: (1.0, 0.0), second.incident.id: (1.0, 0.0)}
    # A vector made by another model is never handed back for comparison.
    assert uow.embeddings.get_many([first.incident.id], provider="fake-gemini", model="v2") == {}

    provider.asked.clear()
    clock.advance(5 * MIN)
    service.similar_incidents(who(uow, CHITRA), title="Fees", description="", service_id=FEES)
    assert provider.asked == ["Fees"]  # only the new text; the two incidents came from the store


def test_BR09_an_unreachable_provider_falls_back_to_tfidf_and_stores_nothing(
    uow: InMemoryUnitOfWork, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    service = make_service(uow, clock, Unreachable())
    first = report(service, uow, ASHA, "Fee portal down", "The fee payment portal will not load")
    clock.advance(5 * MIN)
    second = report(service, uow, BILAL, "Fee portal is down", "Fee payment portal does not load")
    assert ids(second.possible_duplicates) == [first.incident.id]
    assert "unreachable" in caplog.text
    assert uow.embeddings.get_many([first.incident.id], provider="tfidf", model="tfidf-v1") == {}


def test_the_offline_provider_failing_is_not_swallowed(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    class Broken(TfIdfEmbeddings):
        def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
            raise NetworkFailureError

    broken = Broken()
    detector = DuplicateDetector(uow, clock, broken, fallback=broken)
    service = make_service(uow, clock)
    report(service, uow, ASHA, "Fee portal down")
    with pytest.raises(NetworkFailureError):
        detector.check(title="Fee portal", description="", service_id=FEES, reported_at=clock.now())
