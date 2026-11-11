"""Historical incidents for the dashboards, generated from a seeded RNG.

Every incident is driven through the real aggregate methods on a FakeClock walking forward from
its creation time, so the lifecycle, the SLA clock, the audit-worthy events and the resolution
times are all ones the system could really have produced. Nothing is written straight into a
column. A fixed seed means two machines generate byte-identical history.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from random import Random

from app.core.clock import FakeClock
from app.domain.catalogue import Category, ITService
from app.domain.incident import CancelReason, Incident, IncidentFactory
from app.domain.priority import Priority, PriorityStrategy
from app.domain.sla import SLAPolicyBook, SLATarget
from app.domain.users import Technician
from app.seed import people

HISTORY_SIZE = 420  # blueprint §9 asks for 300-500
HISTORY_DAYS = 120
RESOLUTION_SUMMARIES: tuple[str, ...] = (
    "Restarted the affected service and confirmed the user could work again.",
    "Replaced the faulty hardware and tested it with the user.",
    "Cleared the stuck queue and added monitoring for the same symptom.",
    "Corrected the configuration and documented the change.",
    "Reset the account and walked the user through signing in again.",
    "Applied the vendor patch after testing it on a spare machine.",
    "Freed disk space on the node and tuned the slow query behind it.",
    "Re-provisioned the certificate and reloaded the load balancer.",
)
REJECTION_REASONS: tuple[str, ...] = (
    "It worked for an hour and then failed again.",
    "The problem is back this morning.",
    "That fixed the laptop but not the printer.",
)
INFO_QUESTIONS: tuple[str, ...] = (
    "Which building and room are you in?",
    "Does it happen on another device as well?",
    "Can you send the exact error message?",
)
INFO_ANSWERS: tuple[str, ...] = (
    "Library, first floor, near the help desk.",
    "Yes, my colleague sees the same thing.",
    "It says 'connection timed out' after about a minute.",
)
WORK_NOTES: tuple[str, ...] = (
    "Reproduced the problem on a test account.",
    "Checked the logs; nothing unusual before the failure.",
    "Escalated to the vendor and waiting for a reply.",
    "Applied a temporary workaround while investigating.",
)

#: One phrasing per category, matching the category's own keywords.
REPORTS: dict[str, tuple[tuple[str, str], ...]] = {
    "Network": (
        ("Wi-Fi keeps dropping", "The wifi connection drops every few minutes in the library."),
        ("Internet is very slow", "Pages take a minute to load on the campus network today."),
        ("Cannot reach any site", "DNS seems broken; nothing resolves from my office."),
    ),
    "Account and Access": (
        ("Account locked out", "My account is locked after I mistyped my password."),
        ("Cannot sign in to SSO", "The login page keeps returning me to the start."),
        ("MFA prompt never arrives", "No mfa notification reaches my phone when I log in."),
    ),
    "Email": (
        ("Mailbox is full", "My mailbox will not accept new email since this morning."),
        ("Attachment will not open", "An attachment in Outlook fails to download."),
        ("Legitimate mail marked spam", "Email from the department lands in spam."),
    ),
    "Software": (
        ("Application crashes on start", "The application crashes as soon as I open it."),
        ("Need software installed", "Please install the statistics software on my laptop."),
        ("Licence has expired", "The licence prompt blocks me from working."),
    ),
    "Hardware": (
        ("Laptop will not charge", "The battery stays at zero even with the dock connected."),
        ("Monitor shows no picture", "My monitor is black although the laptop is on."),
        ("Keyboard keys stuck", "Several keyboard keys stopped responding."),
    ),
    "Printing": (
        ("Printer jams every page", "The printer jams and the print queue is stuck."),
        ("Toner warning blocks printing", "It refuses to print and asks for toner."),
        ("Cannot scan to email", "The scan option fails with an error."),
    ),
    "Web Application": (
        ("Portal shows an error", "The portal returns an error page when I open my records."),
        ("Page times out", "The website times out before anything loads."),
        ("Upload never finishes", "Uploading a file to the portal hangs at 99 per cent."),
    ),
    "Database": (
        ("Report is extremely slow", "A report that used to take seconds now runs for minutes."),
        ("Data looks wrong", "The data in yesterday's export does not match the portal."),
        ("Backup job failed", "The nightly database backup reported a failure."),
    ),
    "Security": (
        ("Phishing email received", "A suspicious email asks for my password."),
        ("Possible malware on laptop", "My laptop shows pop-ups and may have a virus."),
        ("Suspicious login alert", "I was told someone signed in from another country."),
    ),
    "Payments": (
        ("Fee payment failed", "My fee payment failed but the amount left my account."),
        ("No receipt after payment", "The payment went through and no receipt arrived."),
        ("Refund has not arrived", "A refund promised two weeks ago is still missing."),
    ),
}

#: Which services a category's incidents plausibly land on.
SERVICES_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "Network": ("Campus Wi-Fi", "Campus Network Core", "VPN"),
    "Account and Access": ("Identity Provider", "VPN", "Student Information System"),
    "Email": ("Campus Email",),
    "Software": ("Lab Workstations",),
    "Hardware": ("Lab Workstations", "Printing Service"),
    "Printing": ("Printing Service",),
    "Web Application": (
        "Learning Management System",
        "Library Portal",
        "Student Information System",
        "Exam Portal",
        "Hostel Management",
    ),
    "Database": ("Database Cluster", "Student Information System"),
    "Security": ("Identity Provider", "Campus Network Core", "Lab Workstations"),
    "Payments": ("Fee Payment Portal",),
}


@dataclass(frozen=True, slots=True)
class Outcome:
    """How far an incident got, and how the RNG chose to get it there."""

    name: str
    weight: int


#: The mix that makes every dashboard non-empty: open queues, closed work, and failures.
OUTCOMES: tuple[Outcome, ...] = (
    Outcome("closed_verified", 44),
    Outcome("closed_auto", 16),
    Outcome("verified", 8),
    Outcome("resolved", 8),
    Outcome("in_progress", 8),
    Outcome("on_hold", 5),
    Outcome("acknowledged", 4),
    Outcome("assigned", 3),
    Outcome("new", 2),
    Outcome("cancelled", 2),
)


@dataclass(frozen=True, slots=True)
class Catalogue:
    """What the generator needs to look up while it builds an incident."""

    categories: Sequence[Category]
    services: Sequence[ITService]
    technicians: Sequence[Technician]
    skill_names: dict[int, str]
    policies: SLAPolicyBook
    strategy: PriorityStrategy


class HistoryGenerator:
    """Builds the historical incidents, one lifecycle at a time."""

    def __init__(self, catalogue: Catalogue, now: datetime, seed: int = 20261106) -> None:
        self.__catalogue = catalogue
        self.__now = now
        self.__rng = Random(seed)  # noqa: S311 - demo data, not cryptography
        self.__by_name = {service.name: service for service in catalogue.services}
        self.__categories = {category.name: category for category in catalogue.categories}
        self.__ids_by_service: dict[int, list[str]] = {}

    def generate(
        self, next_sequence: Callable[[int], int], count: int = HISTORY_SIZE
    ) -> list[Incident]:
        """``count`` incidents, oldest first, each one already lived through its lifecycle.

        Numbers come from ``next_sequence`` — the repository's own per-year counter — so the
        seeded ids are allocated exactly as the application allocates them, and the first
        incident a user reports afterwards continues the series instead of colliding with it.
        """
        outcomes = self.__outcome_sequence(count)
        built = []
        for index in range(count):
            incident = self.__one(index, count, outcomes[index], next_sequence)
            self.__ids_by_service.setdefault(incident.service_id, []).append(incident.id)
            built.append(incident)
        return built

    # ------------------------------------------------------------ internals
    def __outcome_sequence(self, count: int) -> list[str]:
        pool = [outcome.name for outcome in OUTCOMES for _ in range(outcome.weight)]
        chosen = [pool[self.__rng.randrange(len(pool))] for _ in range(count)]
        # The newest few are deliberately open, so the demo queues are never empty.
        open_tail = ["new", "assigned", "acknowledged", "in_progress", "on_hold", "resolved"]
        if count >= len(open_tail):
            chosen[-len(open_tail) :] = open_tail
        return chosen

    def __created_at(self, index: int, count: int) -> datetime:
        """Spread creation over the window, newest last, with office-hours jitter."""
        share = (index + 1) / (count + 1)
        days_ago = HISTORY_DAYS * (1 - share)
        start = self.__now - timedelta(days=days_ago)
        return start.replace(
            hour=self.__rng.randrange(8, 19),
            minute=self.__rng.randrange(0, 60),
            second=0,
            microsecond=0,
        )

    def __one(
        self, index: int, count: int, outcome: str, next_sequence: Callable[[int], int]
    ) -> Incident:
        category = self.__categories[self.__rng.choice(list(REPORTS))]
        service = self.__by_name[self.__rng.choice(SERVICES_BY_CATEGORY[category.name])]
        title, description = self.__rng.choice(REPORTS[category.name])
        impact, urgency = self.__factors(service)
        clock = FakeClock(self.__created_at(index, count))
        incident = IncidentFactory.create(
            sequence=next_sequence(clock.now().year),
            clock=clock,
            reporter_id=self.__reporter_id(),
            title=title,
            description=description,
            service_id=service.id,
            impact=impact,
            urgency=urgency,
        )
        assessment = self.__catalogue.strategy.assess(
            impact, urgency, service.criticality, category.minimum_priority
        )
        incident.prioritise(assessment, clock)
        target, _ = self.__catalogue.policies.target_or_default(
            service.sla_tier, assessment.priority
        )
        incident.apply_sla(target)
        self.__live(incident, clock, category, assessment.priority, target, outcome, service.id)
        return incident

    def __factors(self, service: ITService) -> tuple[int, int]:
        """Critical services draw higher impact, so P1s cluster where they should."""
        weights = (1, 2, 3) if service.criticality == 3 else (3, 2, 1)
        impact = self.__rng.choices((1, 2, 3), weights=weights)[0]
        urgency = self.__rng.choices((1, 2, 3), weights=(3, 3, 2))[0]
        return impact, urgency

    def __reporter_id(self) -> int:
        return self.__rng.choice(people.EMPLOYEES).user_id

    def __technician_for(self, category: Category) -> Technician:
        """An available technician who has the category's skill, else anyone available."""
        wanted = self.__catalogue.skill_names.get(category.required_skill_id or -1)
        able = [
            t
            for t in self.__catalogue.technicians
            if t.available and t.active and (wanted is None or wanted in t.skills)
        ]
        pool = able or [t for t in self.__catalogue.technicians if t.available and t.active]
        return self.__rng.choice(pool)

    def __live(
        self,
        incident: Incident,
        clock: FakeClock,
        category: Category,
        priority: Priority,
        target: SLATarget,
        outcome: str,
        service_id: int,
    ) -> None:
        """Walk the incident through the lifecycle its outcome asks for."""
        if outcome == "new":
            return
        clock.advance(self.__fraction(target.response, 0.05, 0.3))
        incident.classify(category.id, None, clock)
        if outcome == "cancelled":
            self.__cancel(incident, clock, service_id)
            return

        technician = self.__technician_for(category)
        incident.assign(technician.id, None, clock)
        if outcome == "assigned":
            return

        # One incident in six answers late, which is what makes SLA compliance interesting.
        late = self.__rng.random() < 0.17
        clock.advance(
            self.__fraction(target.response, 1.1, 2.4)
            if late
            else self.__fraction(target.response, 0.2, 0.9)
        )
        if late and priority in (Priority.P1, Priority.P2):
            incident.escalate(self.__escalation_owner(technician).id, 1, None, clock)
        incident.acknowledge(technician.id, clock)
        if outcome == "acknowledged":
            return

        incident.start(technician.id, clock)
        clock.advance(self.__fraction(target.resolution, 0.05, 0.3))
        incident.add_note(technician.id, clock, self.__rng.choice(WORK_NOTES))
        if outcome == "in_progress":
            return

        if outcome == "on_hold" or self.__rng.random() < 0.25:
            incident.hold(technician.id, clock, self.__rng.choice(INFO_QUESTIONS))
            if outcome == "on_hold":
                return
            clock.advance(timedelta(hours=self.__rng.randrange(1, 20)))
            incident.provide_info(incident.reporter_id, clock, self.__rng.choice(INFO_ANSWERS))

        clock.advance(self.__fraction(target.resolution, 0.3, 1.4))
        incident.resolve(technician.id, clock, self.__rng.choice(RESOLUTION_SUMMARIES))
        if outcome == "resolved":
            return

        if self.__rng.random() < 0.12:  # the fix did not hold: reopen, fix again
            clock.advance(timedelta(hours=self.__rng.randrange(2, 30)))
            incident.reject(incident.reporter_id, clock, self.__rng.choice(REJECTION_REASONS))
            clock.advance(self.__fraction(target.resolution, 0.2, 0.8))
            incident.resolve(technician.id, clock, self.__rng.choice(RESOLUTION_SUMMARIES))

        if outcome == "closed_auto":
            clock.advance(timedelta(hours=72, minutes=1))
            incident.auto_close(clock)
            return

        clock.advance(timedelta(hours=self.__rng.randrange(1, 40)))
        incident.verify(incident.reporter_id, clock, self.__rating(), self.__comment())
        if outcome == "verified":
            return
        clock.advance(timedelta(hours=self.__rng.randrange(1, 12)))
        incident.close(technician.id, clock)

    def __cancel(self, incident: Incident, clock: FakeClock, service_id: int) -> None:
        """Most cancellations are withdrawals; some are confirmed duplicates (D-005)."""
        earlier = self.__ids_by_service.get(service_id, [])
        if earlier and self.__rng.random() < 0.45:
            parent = self.__rng.choice(earlier)
            incident.cancel(incident.reporter_id, clock, CancelReason.DUPLICATE, parent)
        else:
            incident.cancel(incident.reporter_id, clock, CancelReason.WITHDRAWN)

    def __escalation_owner(self, technician: Technician) -> Technician:
        """The lead of the technician's team (D-004), or the technician if there is none."""
        leads = [
            t
            for t in self.__catalogue.technicians
            if t.team_id == technician.team_id and t.escalation_level == 1 and t.id != technician.id
        ]
        return leads[0] if leads else technician

    def __fraction(self, target: timedelta, low: float, high: float) -> timedelta:
        return target * self.__rng.uniform(low, high)

    def __rating(self) -> int:
        return self.__rng.choices((1, 2, 3, 4, 5), weights=(1, 2, 8, 20, 24))[0]

    def __comment(self) -> str:
        return self.__rng.choice(
            ("Thanks for the quick help.", "Sorted, thank you.", "", "Took a while but fixed.")
        )
