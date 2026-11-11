"""Search scoping and CSV export (blueprint §9, BR-01).

What a repository cannot decide is who is allowed to see the results. These tests send the
widest possible query as each role and check what comes back.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import FakeClock
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.errors import InvalidUserInputError
from app.domain.incident import Incident, IncidentFactory
from app.domain.permissions import Role
from app.domain.priority import Priority, PriorityAssessment
from app.domain.search import CSV_EXPORT_LIMIT, MAX_PAGE_SIZE, IncidentQuery
from app.domain.sla import SLATarget, default_policies
from app.domain.users import User, UserFactory
from app.domain.value_objects import SkillSet
from app.repositories.memory import InMemoryUnitOfWork
from app.services.search import CSV_HEADER, SearchService

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
TARGET = SLATarget(timedelta(minutes=15), timedelta(hours=4))
DEVIKA, OTHER, TECH, TECH2, OUTSIDER, LEAD, ADMIN = 1, 2, 3, 4, 5, 6, 7
WIFI = 1


@pytest.fixture
def uow() -> InMemoryUnitOfWork:
    unit = InMemoryUnitOfWork()
    unit.catalogue.save_skill(Skill(1, "networking"))
    unit.catalogue.save_category(Category(1, "Network", keywords=("wifi",)))
    unit.catalogue.save_service(ITService(WIFI, "Campus Wi-Fi", criticality=2))
    unit.catalogue.save_policies(default_policies())
    unit.catalogue.save_team(Team(1, "Network Operations"))
    unit.catalogue.save_team(Team(2, "Service Desk"))

    for user_id, role, name, team_id in (
        (DEVIKA, Role.EMPLOYEE, "Devika Rao", None),
        (OTHER, Role.EMPLOYEE, "Other Person", None),
        (TECH, Role.TECHNICIAN, "Arjun Menon", 1),
        (TECH2, Role.TECHNICIAN, "Tara Sheikh", 1),
        (OUTSIDER, Role.TECHNICIAN, "Imran Shaikh", 2),
        (LEAD, Role.TEAM_LEAD, "Priya Nair", 1),
        (ADMIN, Role.ADMINISTRATOR, "Rahul Verma", None),
    ):
        support = UserFactory.is_support_role(role)
        unit.users.add(
            UserFactory.create(
                role,
                user_id=user_id,
                email=f"u{user_id}@campus.edu",
                full_name=name,
                skills=SkillSet({"networking"}) if support else None,
                experience_level=2 if support else None,
                team_id=team_id if support else None,
            )
        )
    for team_id, members in ((1, (TECH, TECH2, LEAD)), (2, (OUTSIDER,))):
        group = unit.catalogue.get_team(team_id)
        for member in members:
            group.add_member(member)
        unit.catalogue.save_team(group)
    lead_team = unit.catalogue.get_team(1)
    lead_team.set_lead(LEAD)
    unit.catalogue.save_team(lead_team)

    # Four incidents: two reporters, three technicians, one of them in another team.
    _incident(unit, 1, DEVIKA, TECH, "Wi-Fi down in the library")
    _incident(unit, 2, OTHER, TECH2, "Wi-Fi slow in the hostel")
    _incident(unit, 3, DEVIKA, OUTSIDER, "Printer offline in the lab")
    _incident(unit, 4, OTHER, None, "Projector will not turn on")
    return unit


def _incident(
    uow: InMemoryUnitOfWork, sequence: int, reporter: int, technician: int | None, title: str
) -> Incident:
    clock = FakeClock(NOW - timedelta(hours=sequence))
    incident = IncidentFactory.create(
        sequence=sequence,
        clock=clock,
        reporter_id=reporter,
        title=title,
        description=f"{title}, reported by user {reporter}",
        service_id=WIFI,
        impact=2,
        urgency=2,
    )
    incident.prioritise(PriorityAssessment(Priority.P3, 8, "fixture"), clock)
    incident.apply_sla(TARGET)
    incident.classify(1, None, clock)
    if technician is not None:
        incident.assign(technician, None, clock)
        incident.acknowledge(technician, clock)
    uow.incidents.add(incident)
    return incident


@pytest.fixture
def search(uow: InMemoryUnitOfWork) -> SearchService:
    return SearchService(uow, FakeClock(NOW))


def who(uow: InMemoryUnitOfWork, user_id: int) -> User:
    return uow.users.get(user_id)


def found(
    search: SearchService, uow: InMemoryUnitOfWork, user_id: int, **kwargs: object
) -> list[str]:
    query = IncidentQuery(**kwargs)  # type: ignore[arg-type]
    return sorted(i.id for i in search.search(who(uow, user_id), query).items)


# ---------------------------------------------------------------- BR-01 scoping
def test_BR01_an_employee_searching_everything_gets_only_their_own(
    search: SearchService, uow: InMemoryUnitOfWork
) -> None:
    assert found(search, uow, DEVIKA) == ["INC-2026-0001", "INC-2026-0003"]
    assert found(search, uow, OTHER) == ["INC-2026-0002", "INC-2026-0004"]


def test_BR01_an_employee_cannot_widen_the_search_with_filters(
    search: SearchService, uow: InMemoryUnitOfWork
) -> None:
    """Asking for someone else's incidents explicitly must not return them."""
    assert found(search, uow, DEVIKA, reporter_ids=(OTHER,)) == [
        "INC-2026-0001",
        "INC-2026-0003",
    ]
    assert found(search, uow, DEVIKA, assignee_ids=(TECH2,)) == []


def test_a_technician_sees_their_own_queue(search: SearchService, uow: InMemoryUnitOfWork) -> None:
    assert found(search, uow, TECH) == ["INC-2026-0001"]
    assert found(search, uow, OUTSIDER) == ["INC-2026-0003"]
    # Asking about a colleague gives you your own queue back, never theirs.
    assert found(search, uow, TECH, assignee_ids=(TECH2,)) == ["INC-2026-0001"]


def test_a_team_lead_sees_the_whole_team(search: SearchService, uow: InMemoryUnitOfWork) -> None:
    """D-004: the lead's scope is their own team, not every technician."""
    # ...plus INC-0004, which nobody holds yet: "queued for the Team Lead" (§5.3) has to be
    # somewhere a lead can see it (P3 review).
    assert found(search, uow, LEAD) == ["INC-2026-0001", "INC-2026-0002", "INC-2026-0004"]
    assert found(search, uow, LEAD, assignee_ids=(TECH,)) == ["INC-2026-0001"]
    # A technician's queue is still only what they hold.
    assert "INC-2026-0004" not in found(search, uow, TECH)
    # A technician in another team is outside the lead's scope.
    assert found(search, uow, LEAD, assignee_ids=(OUTSIDER,)) == []


def test_an_admin_sees_everything_including_the_unassigned(
    search: SearchService, uow: InMemoryUnitOfWork
) -> None:
    assert found(search, uow, ADMIN) == [
        "INC-2026-0001",
        "INC-2026-0002",
        "INC-2026-0003",
        "INC-2026-0004",
    ]
    assert found(search, uow, ADMIN, reporter_ids=(DEVIKA,)) == [
        "INC-2026-0001",
        "INC-2026-0003",
    ]


def test_scoping_is_visible_on_the_query_itself(
    search: SearchService, uow: InMemoryUnitOfWork
) -> None:
    wide = IncidentQuery()
    assert search.scoped(who(uow, DEVIKA), wide).reporter_ids == (DEVIKA,)
    assert search.scoped(who(uow, TECH), wide).assignee_ids == (TECH,)
    assert search.scoped(who(uow, ADMIN), wide) == wide


# ---------------------------------------------------------------- validation
def test_a_nonsense_query_is_refused_before_it_runs() -> None:
    with pytest.raises(InvalidUserInputError):
        IncidentQuery(limit=0)
    with pytest.raises(InvalidUserInputError):
        IncidentQuery(limit=CSV_EXPORT_LIMIT + 1)
    assert IncidentQuery(limit=MAX_PAGE_SIZE).limit == MAX_PAGE_SIZE
    with pytest.raises(InvalidUserInputError):
        IncidentQuery(offset=-1)
    with pytest.raises(InvalidUserInputError):
        IncidentQuery(created_from=NOW, created_to=NOW - timedelta(days=1))
    with pytest.raises(InvalidUserInputError):
        IncidentQuery(text="x" * 500)


def test_blank_free_text_is_treated_as_no_filter() -> None:
    assert IncidentQuery(text="   ").text is None
    assert IncidentQuery(text="  wifi ").text == "wifi"
    assert IncidentQuery(text="   ").is_filtered is False


# ---------------------------------------------------------------- CSV export (§9)
def test_the_export_has_a_header_and_one_row_per_result(
    search: SearchService, uow: InMemoryUnitOfWork
) -> None:
    csv = search.export_csv(who(uow, ADMIN), IncidentQuery())
    lines = csv.strip().splitlines()
    assert lines[0] == ",".join(CSV_HEADER)
    assert len(lines) == 5  # the header and four incidents
    assert "INC-2026-0001" in csv
    assert "Campus Wi-Fi" in csv
    assert "Devika Rao" in csv
    assert "Arjun Menon" in csv
    assert "Created (IST)" in csv  # §9: stored in UTC, read in IST
    assert csv.endswith("\r\n")  # what a spreadsheet expects


def test_the_export_is_scoped_like_the_search(
    search: SearchService, uow: InMemoryUnitOfWork
) -> None:
    csv = search.export_csv(who(uow, DEVIKA), IncidentQuery())
    assert "INC-2026-0001" in csv
    assert "INC-2026-0002" not in csv
    assert "Other Person" not in csv


def test_the_export_honours_the_filters_and_quotes_commas(
    search: SearchService, uow: InMemoryUnitOfWork
) -> None:
    clock = FakeClock(NOW)
    awkward = IncidentFactory.create(
        sequence=9,
        clock=clock,
        reporter_id=DEVIKA,
        title='Wi-Fi, printers, and the "portal" all down',
        description="Several things at once",
        service_id=WIFI,
        impact=2,
        urgency=2,
    )
    uow.incidents.add(awkward)

    csv = search.export_csv(who(uow, ADMIN), IncidentQuery(text="portal"))
    lines = csv.strip().splitlines()
    assert len(lines) == 2
    assert '"Wi-Fi, printers, and the ""portal"" all down"' in csv


def test_an_empty_result_still_exports_its_header(
    search: SearchService, uow: InMemoryUnitOfWork
) -> None:
    csv = search.export_csv(who(uow, ADMIN), IncidentQuery(text="nothing matches"))
    assert csv.strip() == ",".join(CSV_HEADER)
