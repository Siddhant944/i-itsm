"""A pytest plugin that records every test's outcome and requirements as JSON (P6.3).

Loaded by ``scripts/test_report.py`` with ``-p scripts.pytest_results --results-json PATH``.
A test's requirements are its ``@pytest.mark.req("...")`` markers plus every business-rule
id in its name (AGENTS.md: each BR test's name contains its id, e.g. ``test_BR07_...``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

_BR_IN_NAME = re.compile(r"BR-?(\d{2})")


def requirements_of(item: pytest.Item) -> list[str]:
    """The requirement ids a collected test claims, sorted and de-duplicated."""
    found = {f"BR-{n}" for n in _BR_IN_NAME.findall(item.name)}
    for marker in item.iter_markers("req"):
        found.update(str(arg) for arg in marker.args)
    return sorted(found)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--results-json", default=None, help="write per-test outcomes here")


class _Recorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.tests: dict[str, dict[str, Any]] = {}

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            self.tests[item.nodeid] = {"outcome": "not run", "reqs": requirements_of(item)}

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        entry = self.tests.setdefault(report.nodeid, {"outcome": "not run", "reqs": []})
        if report.when == "call" or (report.when == "setup" and not report.passed):
            outcome = "skipped" if report.skipped else report.outcome
            entry["outcome"] = outcome
            entry["duration"] = round(report.duration, 4)
        elif report.when == "teardown" and report.failed:
            entry["outcome"] = "failed"

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {"exitstatus": int(exitstatus), "tests": self.tests}
        self.path.write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")


def pytest_configure(config: pytest.Config) -> None:
    path = config.getoption("--results-json")
    if path:
        config.pluginmanager.register(_Recorder(Path(path)), "results-json-recorder")
