"""The report's pattern and OOP evidence (P6.2) is generated from the code and kept fresh."""

from pathlib import Path

import pytest

from scripts import gen_pattern_table

GENERATED = Path(__file__).resolve().parents[4] / "report" / "generated"


@pytest.mark.parametrize("name", sorted(gen_pattern_table.render_all()))
def test_committed_evidence_matches_the_code(name: str) -> None:
    committed = (GENERATED / name).read_text(encoding="utf-8")
    assert committed == gen_pattern_table.render_all()[name], (
        f"report/generated/{name} is stale: run `make report` (or gen_pattern_table.py)"
    )


def test_every_blueprint_pattern_is_documented_in_a_docstring() -> None:
    found = " ".join(use.pattern for use in gen_pattern_table.pattern_uses())
    for pattern in (
        "State",
        "Strategy",
        "Observer",
        "Factory",
        "Repository",
        "Adapter",
        "Chain of Responsibility",
        "Template Method",
        "Facade",
    ):
        assert pattern in found, pattern


def test_the_counts_match_the_hierarchies_the_tests_pin() -> None:
    measures = {e.concept: e.measure for e in gen_pattern_table.oop_evidence()}
    inheritance = measures["Inheritance (true is-a only)"]
    assert "User has 5 subclasses" in inheritance
    assert "IncidentState has 10 concrete states" in inheritance
    assert "8 groups and 14 specific errors" in inheritance


def test_committed_versions_match_the_lock_files() -> None:
    from scripts import gen_versions

    committed = (GENERATED / "versions.tex").read_text(encoding="utf-8")
    assert committed == gen_versions.render(), (
        "report/generated/versions.tex is stale: run `make report` (or gen_versions.py)"
    )
