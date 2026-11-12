"""Notifications end to end over the in-memory repositories (blueprint §5.4).

The IncidentService's post-commit dispatcher drives this service, so the tests report and work
real incidents and then check who was told what, on which channel, and what happened when the
channel refused.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import FakeClock
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.errors import (
    InvalidUserInputError,
    NetworkFailureError,
    UnauthorizedOperationError,
)
from app.domain.notifications import (
    MAX_SEND_ATTEMPTS,
    ChannelName,
    DeliveryStatus,
    Notification,
    NotificationEvent,
)
from app.domain.permissions import Role
from app.domain.ports import ChatSender, EmailSender, NotificationChannel, OutgoingMessage
from app.domain.priority import Priority
from app.domain.rule_advisor import RuleBasedAdvisor
from app.domain.sla import default_policies
from app.domain.users import User, UserFactory
from app.domain.value_objects import SkillSet
from app.repositories.memory import InMemoryUnitOfWork
from app.services.dispatcher import PostCommitDispatcher
from app.services.incident_service import IncidentService
from app.services.notifications import (
    ChannelFactory,
    EmailChannel,
    InAppChannel,
    default_factory,
)
from app.services.notifications.channels import TelegramChannel
from app.services.notifications.service import NotificationService
from app.services.sla_monitor import AUTO_CLOSE_AFTER, SLAMonitor

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
REPORTER, TECH, LEAD, ADMIN = 1, 2, 3, 4
WIFI, PORTAL = 1, 2
NETWORK, PAYMENTS = 1, 2


class RecordingEmailSender(EmailSender):
    """A fake SMTP: remembers what it was asked to send, or refuses if told to."""

    name = "recording"

    def __init__(self, *, fail_times: int = 0) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.__fail_times = fail_times
        self.attempts = 0

    def send(self, to: str, subject: str, body: str) -> None:
        self.attempts += 1
        if self.attempts <= self.__fail_times:
            msg = "the mail server refused the connection"
            raise NetworkFailureError(msg)
        self.sent.append((to, subject, body))


class RefusingChannel(NotificationChannel):
    name = "telegram"

    def send(self, message: OutgoingMessage) -> None:
        msg = "Telegram is unreachable"
        raise NetworkFailureError(msg)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def uow() -> InMemoryUnitOfWork:
    unit = InMemoryUnitOfWork()
    unit.catalogue.save_skill(Skill(1, "networking"))
    unit.catalogue.save_category(
        Category(NETWORK, "Network", required_skill_id=1, keywords=("wifi", "network"))
    )
    unit.catalogue.save_category(
        Category(PAYMENTS, "Payments", keywords=("fee", "payment"), minimum_priority=Priority.P1)
    )
    unit.catalogue.save_service(ITService(WIFI, "Campus Wi-Fi", criticality=1))
    unit.catalogue.save_service(ITService(PORTAL, "Fee Payment Portal", criticality=3))
    unit.catalogue.save_policies(default_policies())
    unit.catalogue.save_team(Team(1, "Network Operations"))

    unit.users.add(
        UserFactory.create(
            Role.EMPLOYEE, user_id=REPORTER, email="devika@campus.edu", full_name="Devika Rao"
        )
    )
    unit.users.add(
        UserFactory.create(
            Role.TECHNICIAN,
            user_id=TECH,
            email="arjun@campus.edu",
            full_name="Arjun Menon",
            skills=SkillSet({"networking"}),
            team_id=1,
        )
    )
    unit.users.add(
        UserFactory.create(
            Role.TEAM_LEAD,
            user_id=LEAD,
            email="priya@campus.edu",
            full_name="Priya Nair",
            skills=SkillSet({"networking"}),
            experience_level=3,
            team_id=1,
        )
    )
    unit.users.add(
        UserFactory.create(
            Role.ADMINISTRATOR, user_id=ADMIN, email="rahul@campus.edu", full_name="Rahul Verma"
        )
    )
    team = unit.catalogue.get_team(1)
    team.add_member(TECH)
    team.add_member(LEAD)
    team.set_lead(LEAD)
    unit.catalogue.save_team(team)
    return unit


@pytest.fixture
def mailer() -> RecordingEmailSender:
    return RecordingEmailSender()


@pytest.fixture
def channels(uow: InMemoryUnitOfWork, mailer: RecordingEmailSender) -> ChannelFactory:
    return ChannelFactory(
        {
            ChannelName.IN_APP: InAppChannel(),
            ChannelName.EMAIL: EmailChannel(mailer, lambda user_id: _address(uow, user_id)),
        }
    )


def _address(uow: InMemoryUnitOfWork, user_id: int) -> str | None:
    try:
        return str(uow.users.get(user_id).email)
    except Exception:
        return None


@pytest.fixture
def notifier(
    uow: InMemoryUnitOfWork, clock: FakeClock, channels: ChannelFactory
) -> NotificationService:
    return NotificationService(uow, clock, channels)


@pytest.fixture
def incidents(
    uow: InMemoryUnitOfWork, clock: FakeClock, notifier: NotificationService
) -> IncidentService:
    return IncidentService(
        uow,
        clock,
        dispatcher=PostCommitDispatcher([notifier.on_event]),
        advisor=RuleBasedAdvisor(),
    )


def who(uow: InMemoryUnitOfWork, user_id: int) -> User:
    return uow.users.get(user_id)


def sent_to(uow: InMemoryUnitOfWork, event: NotificationEvent) -> set[int]:
    return {n.user_id for n in _all(uow) if n.event is event and n.channel is ChannelName.IN_APP}


def _all(uow: InMemoryUnitOfWork) -> list[Notification]:
    found: list[Notification] = []
    index = 1
    while True:
        try:
            found.append(uow.notifications.get(index))
        except Exception:
            return found
        index += 1


def report_low(incidents: IncidentService, uow: InMemoryUnitOfWork) -> str:
    """A P4 on a Bronze service: no Team Lead on creation, no Telegram on assignment."""
    return incidents.report(
        who(uow, REPORTER),
        title="Wi-Fi is slow",
        description="The wifi network is slow in my office",
        service_id=WIFI,
        impact=1,
        urgency=1,
    ).incident.id


def report_high(incidents: IncidentService, uow: InMemoryUnitOfWork) -> str:
    """A P1: the Team Lead hears about it as soon as it is reported."""
    return incidents.report(
        who(uow, REPORTER),
        title="Fee payment failed",
        description="The fee payment portal rejects every payment",
        service_id=PORTAL,
        impact=3,
        urgency=3,
        category_id=PAYMENTS,
    ).incident.id


# ---------------------------------------------------------------- T-NOTIF recipients
def test_T_NOTIF_a_new_low_priority_incident_tells_only_the_reporter(
    incidents: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    report_low(incidents, uow)
    assert sent_to(uow, NotificationEvent.CREATED) == {REPORTER}


def test_T_NOTIF_a_new_p1_also_tells_the_team_lead(
    incidents: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report_high(incidents, uow)
    assert uow.incidents.get(incident_id).priority is Priority.P1
    assert sent_to(uow, NotificationEvent.CREATED) == {REPORTER, LEAD}


def test_T_NOTIF_assignment_tells_the_reporter_and_the_assignee(
    incidents: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report_low(incidents, uow)
    assignee = uow.incidents.get(incident_id).assignee_id
    assert assignee is not None
    assert sent_to(uow, NotificationEvent.ASSIGNED) == {REPORTER, assignee}


def test_T_NOTIF_telegram_is_only_attempted_for_p1_and_p2(
    incidents: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    report_low(incidents, uow)
    low_channels = {n.channel for n in _all(uow) if n.event is NotificationEvent.ASSIGNED}
    assert low_channels == {ChannelName.IN_APP, ChannelName.EMAIL}

    report_high(incidents, uow)
    high_channels = {n.channel for n in _all(uow) if n.event is NotificationEvent.ASSIGNED}
    assert ChannelName.TELEGRAM in high_channels


def test_T_NOTIF_asking_for_information_tells_the_reporter_and_answering_tells_the_technician(
    incidents: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report_low(incidents, uow)
    assignee = uow.incidents.get(incident_id).assignee_id
    assert assignee is not None
    technician = who(uow, assignee)
    incidents.acknowledge(technician, incident_id)
    incidents.start(technician, incident_id)
    incidents.request_information(technician, incident_id, "Which building are you in?")
    assert sent_to(uow, NotificationEvent.INFO_REQUESTED) == {REPORTER}

    incidents.provide_information(who(uow, REPORTER), incident_id, "The library")
    assert sent_to(uow, NotificationEvent.INFO_PROVIDED) == {assignee}


def test_T_NOTIF_resolving_asks_the_reporter_to_confirm_and_closing_tells_both(
    incidents: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report_low(incidents, uow)
    assignee = uow.incidents.get(incident_id).assignee_id
    assert assignee is not None
    technician = who(uow, assignee)
    incidents.acknowledge(technician, incident_id)
    incidents.start(technician, incident_id)
    incidents.resolve(technician, incident_id, "Replaced the access point")
    assert sent_to(uow, NotificationEvent.RESOLVED) == {REPORTER}

    incidents.verify(who(uow, REPORTER), incident_id, rating=5)
    incidents.close(technician, incident_id)
    assert sent_to(uow, NotificationEvent.CLOSED) == {REPORTER, assignee}
    closed_channels = {n.channel for n in _all(uow) if n.event is NotificationEvent.CLOSED}
    assert closed_channels == {ChannelName.IN_APP}  # §5.4: closing is in-app only


def test_a_priority_override_is_news_but_the_first_assessment_is_not(
    incidents: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report_low(incidents, uow)
    assert sent_to(uow, NotificationEvent.PRIORITY_CHANGED) == set()

    incidents.override_priority(who(uow, ADMIN), incident_id, Priority.P1, reason="Exam tomorrow")
    assignee = uow.incidents.get(incident_id).assignee_id
    assert assignee is not None
    assert sent_to(uow, NotificationEvent.PRIORITY_CHANGED) == {REPORTER, assignee}
    override = next(n for n in _all(uow) if n.event is NotificationEvent.PRIORITY_CHANGED)
    assert "Exam tomorrow" in override.body


def test_an_escalation_tells_its_new_owner(
    uow: InMemoryUnitOfWork, clock: FakeClock, notifier: NotificationService
) -> None:
    """§5.4 Escalated: the new owner hears about it, through the monitor that does the work."""
    incidents = IncidentService(
        uow,
        clock,
        dispatcher=PostCommitDispatcher([notifier.on_event]),
        advisor=RuleBasedAdvisor(),
    )
    incident_id = report_high(incidents, uow)
    assert uow.incidents.get(incident_id).priority is Priority.P1

    # Nobody acknowledges it, so the monitor escalates it to the team's lead after 5 minutes.
    monitor = SLAMonitor(uow, clock, notify=notifier.notify)
    clock.advance(timedelta(minutes=6))
    report = monitor.tick()

    assert [step.incident_id for step in report.escalations] == [incident_id]
    # The lead is the most experienced technician here, so auto-assignment gave it to them.
    # Escalating to level 1 would hand it back to the same person, so §5.5's chain carries on
    # to the administrator; whoever ends up owning it is who hears about it.
    owner = uow.incidents.get(incident_id).assignee_id
    assert owner == ADMIN
    assert sent_to(uow, NotificationEvent.ESCALATED) == {owner}
    escalation = next(n for n in _all(uow) if n.event is NotificationEvent.ESCALATED)
    assert "level 2" in escalation.body
    assert incident_id in escalation.subject


def test_an_auto_closed_incident_tells_its_reporter(
    uow: InMemoryUnitOfWork, clock: FakeClock, notifier: NotificationService
) -> None:
    """§5.4 Closed, reached through BR-03's 72-hour auto-close rather than by a person."""
    incidents = IncidentService(
        uow,
        clock,
        dispatcher=PostCommitDispatcher([notifier.on_event]),
        advisor=RuleBasedAdvisor(),
    )
    incident_id = report_low(incidents, uow)
    assignee = uow.incidents.get(incident_id).assignee_id
    assert assignee is not None
    technician = who(uow, assignee)
    incidents.acknowledge(technician, incident_id)
    incidents.start(technician, incident_id)
    incidents.resolve(technician, incident_id, "Replaced the access point")

    monitor = SLAMonitor(uow, clock, notify=notifier.notify)
    clock.advance(AUTO_CLOSE_AFTER + timedelta(minutes=1))
    assert monitor.tick().auto_closed == (incident_id,)

    assert REPORTER in sent_to(uow, NotificationEvent.CLOSED)
    closed = next(n for n in _all(uow) if n.event is NotificationEvent.CLOSED)
    assert "72 hours" in closed.body


# ---------------------------------------------------------------- the message itself
def test_the_message_names_the_incident_and_reads_as_plain_language(
    incidents: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    incident_id = report_low(incidents, uow)
    created = next(n for n in _all(uow) if n.event is NotificationEvent.CREATED)
    assert incident_id in created.subject
    assert "Wi-Fi is slow" in created.body
    assert "IST" in created.body  # §9: shown in IST, stored in UTC
    assert "INC" in created.body


def test_the_email_goes_to_the_persons_address(
    incidents: IncidentService, uow: InMemoryUnitOfWork, mailer: RecordingEmailSender
) -> None:
    report_low(incidents, uow)
    addresses = {to for to, _, _ in mailer.sent}
    assert "devika@campus.edu" in addresses


# ---------------------------------------------------------------- delivery, retries, fallback
def test_a_notification_is_stored_before_it_is_sent_and_marked_afterwards(
    incidents: IncidentService, uow: InMemoryUnitOfWork
) -> None:
    report_low(incidents, uow)
    delivered = [n for n in _all(uow) if n.channel is ChannelName.EMAIL]
    assert delivered
    assert all(n.status is DeliveryStatus.SENT for n in delivered)
    assert all(n.attempts == 1 for n in delivered)
    assert all(n.sent_at == NOW for n in delivered)


def test_a_flaky_mail_server_is_retried_and_then_succeeds(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """§5.4: a failed send is retried up to three times."""
    flaky = RecordingEmailSender(fail_times=2)
    channels = ChannelFactory(
        {
            ChannelName.IN_APP: InAppChannel(),
            ChannelName.EMAIL: EmailChannel(flaky, lambda user_id: _address(uow, user_id)),
        }
    )
    notifier = NotificationService(uow, clock, channels)
    incidents = IncidentService(
        uow,
        clock,
        dispatcher=PostCommitDispatcher([notifier.on_event]),
        advisor=RuleBasedAdvisor(),
    )
    report_low(incidents, uow)

    first_email = next(n for n in _all(uow) if n.channel is ChannelName.EMAIL)
    assert first_email.attempts == MAX_SEND_ATTEMPTS
    assert first_email.status is DeliveryStatus.SENT
    assert flaky.sent


def test_a_dead_channel_gives_up_after_three_attempts_and_blocks_nothing(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    channels = ChannelFactory(
        {ChannelName.IN_APP: InAppChannel(), ChannelName.TELEGRAM: RefusingChannel()}
    )
    notifier = NotificationService(uow, clock, channels)
    incidents = IncidentService(
        uow,
        clock,
        dispatcher=PostCommitDispatcher([notifier.on_event]),
        advisor=RuleBasedAdvisor(),
    )
    incident_id = report_high(incidents, uow)

    telegram = [n for n in _all(uow) if n.channel is ChannelName.TELEGRAM]
    assert telegram
    assert all(n.attempts == MAX_SEND_ATTEMPTS for n in telegram)
    assert all(n.status is DeliveryStatus.FAILED for n in telegram)
    # The incident itself is untouched by the failures.
    assert uow.incidents.get(incident_id).assignee_id is not None


def test_a_channel_this_deployment_lacks_is_recorded_not_retried(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """With no Telegram configured there is nothing to retry, and nothing fails loudly."""
    channels = ChannelFactory({ChannelName.IN_APP: InAppChannel()})
    notifier = NotificationService(uow, clock, channels)
    incidents = IncidentService(
        uow,
        clock,
        dispatcher=PostCommitDispatcher([notifier.on_event]),
        advisor=RuleBasedAdvisor(),
    )
    report_high(incidents, uow)

    unroutable = [n for n in _all(uow) if n.channel is not ChannelName.IN_APP]
    assert unroutable
    assert all(n.status is DeliveryStatus.FAILED for n in unroutable)
    assert all(n.attempts == 0 for n in unroutable)
    assert any(n.status is DeliveryStatus.SENT for n in _all(uow))


# ---------------------------------------------------------------- the bell
def test_the_bell_counts_and_lists_only_this_persons_in_app_notifications(
    incidents: IncidentService, uow: InMemoryUnitOfWork, notifier: NotificationService
) -> None:
    report_low(incidents, uow)
    reporter_summary = notifier.summary(who(uow, REPORTER))
    assert reporter_summary.unread >= 2  # created and assigned
    assert all(n.user_id == REPORTER for n in reporter_summary.latest)
    assert all(n.channel is ChannelName.IN_APP for n in reporter_summary.latest)

    newest, older = reporter_summary.latest[0], reporter_summary.latest[-1]
    assert (newest.id or 0) >= (older.id or 0)


def test_reading_a_notification_lowers_the_count(
    incidents: IncidentService, uow: InMemoryUnitOfWork, notifier: NotificationService
) -> None:
    report_low(incidents, uow)
    reporter = who(uow, REPORTER)
    before = notifier.summary(reporter).unread
    first = notifier.summary(reporter).latest[0]
    assert first.id is not None

    read = notifier.mark_read(reporter, first.id)
    assert read.is_read is True
    assert notifier.summary(reporter).unread == before - 1


def test_someone_elses_notification_cannot_be_read(
    incidents: IncidentService, uow: InMemoryUnitOfWork, notifier: NotificationService
) -> None:
    report_low(incidents, uow)
    mine = notifier.summary(who(uow, REPORTER)).latest[0]
    assert mine.id is not None
    with pytest.raises(UnauthorizedOperationError):
        notifier.mark_read(who(uow, ADMIN), mine.id)


def test_a_notification_failure_never_reaches_the_caller(
    uow: InMemoryUnitOfWork, clock: FakeClock
) -> None:
    """§5.4: notifications never block or roll back the change that triggered them."""

    class BrokenChannels(ChannelFactory):
        def get(self, name: ChannelName) -> NotificationChannel | None:
            msg = "the whole notification subsystem is broken"
            raise RuntimeError(msg)

    notifier = NotificationService(uow, clock, BrokenChannels({}))
    incidents = IncidentService(
        uow,
        clock,
        dispatcher=PostCommitDispatcher([notifier.on_event]),
        advisor=RuleBasedAdvisor(),
    )
    incident_id = report_low(incidents, uow)
    assert uow.incidents.get(incident_id).assignee_id is not None


# ---------------------------------------------------------------- Telegram (P4.9)
class RecordingChat(ChatSender):
    name = "fake-telegram"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


def test_a_p1_reaches_linked_telegram_chats_and_skips_unlinked_people(
    uow: InMemoryUnitOfWork, clock: FakeClock, mailer: RecordingEmailSender
) -> None:
    chat = RecordingChat()
    lead = next(u for u in uow.users.all() if u.role is Role.TEAM_LEAD)
    lead.link_telegram("555000111")
    uow.users.save(lead)
    notifier = NotificationService(
        uow,
        clock,
        default_factory(
            email=EmailChannel(mailer, lambda user_id: _address(uow, user_id)),
            telegram=TelegramChannel(chat, lambda user_id: uow.users.get(user_id).telegram_chat_id),
        ),
    )
    incidents = IncidentService(
        uow, clock, dispatcher=PostCommitDispatcher([notifier.on_event]), advisor=RuleBasedAdvisor()
    )

    report_low(incidents, uow)
    assert chat.sent == []  # §5.4: Telegram only for P1 and P2

    incident_id = report_high(incidents, uow)
    assert chat.sent, "the linked Team Lead should hear about a new P1"
    assert {chat_id for chat_id, _ in chat.sent} == {"555000111"}
    assert all(incident_id in text for _, text in chat.sent)
    # Unlinked recipients are skipped quietly rather than failed and retried.
    telegram = [n for n in _all(uow) if n.channel is ChannelName.TELEGRAM]
    assert all(n.status is DeliveryStatus.SENT for n in telegram)


def test_a_test_message_needs_a_linked_chat_and_a_configured_bot(
    uow: InMemoryUnitOfWork, clock: FakeClock, notifier: NotificationService
) -> None:
    reporter = who(uow, REPORTER)
    with pytest.raises(NetworkFailureError):  # this deployment has no Telegram channel
        notifier.send_test(reporter, ChannelName.TELEGRAM)

    chat = RecordingChat()
    with_bot = NotificationService(
        uow,
        clock,
        default_factory(telegram=TelegramChannel(chat, lambda _: reporter.telegram_chat_id)),
    )
    with pytest.raises(InvalidUserInputError):
        with_bot.send_test(reporter, ChannelName.TELEGRAM)
    reporter.link_telegram("42")
    with_bot.send_test(reporter, ChannelName.TELEGRAM)
    assert chat.sent == [("42", chat.sent[0][1])]
    assert "I-ITSM test message" in chat.sent[0][1]
