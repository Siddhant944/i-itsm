"""The code-derived diagrams (P6.1) are committed; these tests keep them true to the code."""

from pathlib import Path

import pytest

from app.domain.states import IncidentStatus
from scripts import gen_diagrams

GENERATED = Path(__file__).resolve().parents[4] / "docs" / "diagrams" / "generated"


@pytest.mark.parametrize("name", sorted(gen_diagrams.render_all()))
def test_committed_diagram_matches_the_code(name: str) -> None:
    committed = (GENERATED / name).read_text(encoding="utf-8")
    assert committed == gen_diagrams.render_all()[name], (
        f"docs/diagrams/generated/{name} is stale: run `make diagrams` and commit it"
    )


def test_no_stale_generated_files_are_left_behind() -> None:
    expected = set(gen_diagrams.render_all())
    on_disk = {p.name for p in GENERATED.glob("*.puml")}
    assert on_disk == expected


def test_state_diagram_has_exactly_the_twenty_lifecycle_transitions() -> None:
    pairs = {(source, target) for source, target, _ in gen_diagrams.transitions()}
    assert len(pairs) == 20
    assert (IncidentStatus.RESOLVED, IncidentStatus.CLOSED) in pairs  # BR-03 auto-close
    assert (IncidentStatus.ASSIGNED, IncidentStatus.ASSIGNED) in pairs  # reassign or escalate
    assert (IncidentStatus.NEW, IncidentStatus.CLOSED) not in pairs


def test_er_diagram_draws_every_table_and_marks_one_to_one_links() -> None:
    text = gen_diagrams.er_diagram()
    assert text.count("\nentity ") == 18
    assert "incidents ||--o| resolutions : incident_id" in text
    assert "users |o--o{ incidents : assignee_id" in text


def test_class_diagrams_show_inheritance_through_private_helpers() -> None:
    by_name = {spec.name: spec for spec in gen_diagrams.CLASS_DIAGRAMS}
    states = gen_diagrams.class_diagram(by_name["class-states"])
    assert "NewState --|> IncidentState" in states  # via _Cancellable
    users = gen_diagrams.class_diagram(by_name["class-users"])
    assert "TeamLead --|> Technician" in users
    assert "abstract class User" in users
