"""The documented test cases (P6.3) are well-formed and point at tests that exist."""

import re
from pathlib import Path
from typing import Any

import pytest

from scripts import test_report
from scripts.test_report import CaseFileError, evaluate, load_cases, matching, tex

BACKEND = Path(__file__).resolve().parents[3]


def test_the_committed_cases_cover_every_category_the_requirements_name() -> None:
    cases = load_cases()
    assert len(cases) >= 15
    assert {c.category for c in cases} == set(test_report.CATEGORIES)


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c.id)
def test_every_named_test_exists_in_its_file(case: test_report.Case) -> None:
    for test_id in case.tests:
        path, _, name = test_id.partition("::")
        function = name.split("[")[0]
        source = (BACKEND / path).read_text(encoding="utf-8")
        assert re.search(rf"^def {function}\(", source, re.M), test_id


def test_a_bad_case_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text("cases:\n  - id: TC-01\n    category: normal\n", encoding="utf-8")
    with pytest.raises(CaseFileError, match="missing"):
        load_cases(path)
    path.write_text("cases: []\n", encoding="utf-8")
    with pytest.raises(CaseFileError, match="only 0 cases"):
        load_cases(path)


def test_a_test_id_covers_its_parametrisations_only() -> None:
    run: dict[str, dict[str, Any]] = {
        "a.py::t[1]": {},
        "a.py::t[2]": {},
        "a.py::t_other": {},
        "a.py::t": {},
    }
    assert matching("a.py::t", run) == ["a.py::t[1]", "a.py::t[2]", "a.py::t"]
    assert matching("a.py::t[2]", run) == ["a.py::t[2]"]
    assert matching("a.py::missing", run) == []


def test_status_is_pass_only_when_every_check_passed() -> None:
    case = load_cases()[0]
    test_id = case.tests[0]
    passed = evaluate([case], {test_id: {"outcome": "passed", "reqs": []}})[0]
    assert passed.status == "PASS"
    assert passed.actual == "1 of 1 automated check passed."
    failed = evaluate([case], {test_id: {"outcome": "failed", "reqs": []}})[0]
    assert failed.status == "FAIL"
    with pytest.raises(CaseFileError, match="was not collected"):
        evaluate([case], {})


def test_text_is_escaped_for_latex() -> None:
    assert tex("75 % & ON_HOLD #1 ≥ 10") == r"75 \% \& ON\_HOLD \#1 $\geq$ 10"
