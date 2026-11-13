"""Run the tests and write the report's testing evidence from that real run (P6.3).

1. Reads ``docs/testing/cases.yaml`` (the documented cases) and checks it: unique ids, at
   least 15 cases, all six categories of the requirements, and every named test collected.
2. Runs the whole backend suite once with coverage and the ``pytest_results`` plugin, and the
   frontend's Vitest suite.
3. Writes, from what actually happened:
   * ``report/generated/test-cases.tex`` — each case with its actual result and status;
   * ``report/generated/test-summary.tex`` — totals, coverage, date and commit of the run;
   * ``report/generated/traceability.tex`` — BR-01..BR-10 to the tests that check them;
   * ``docs/testing/test-report.md`` — the same, readable on GitHub.

Usage (from backend/): ``uv run python scripts/test_report.py`` — or ``make test-report``.
``--skip-run`` re-renders from the last run's JSON without running the tests again.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.clock import SystemClock

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
CASES = REPO / "docs" / "testing" / "cases.yaml"
GENERATED = REPO / "report" / "generated"
MARKDOWN = REPO / "docs" / "testing" / "test-report.md"
RUN_DIR = BACKEND / ".test-report"  # git-ignored scratch for the raw results

CATEGORIES = {
    "normal": "Normal operation",
    "boundary": "Boundary condition",
    "invalid": "Invalid input",
    "exception": "Exception",
    "authorisation": "Authorisation",
    "rule": "Business rule",
}
MIN_CASES = 15

#: Blueprint §7, the rule each BR id stands for (kept short for the matrix).
BUSINESS_RULES = {
    "BR-01": "Employees see and act only on their own incidents.",
    "BR-02": "Only the assignee, the escalation owner or an admin works an incident.",
    "BR-03": "Only the reporter verifies or rejects; unverified fixes auto-close after 72 h.",
    "BR-04": "Resolving needs a summary; reopening only from RESOLVED.",
    "BR-05": "Priority is computed; overrides need a reason; category floors apply.",
    "BR-06": "Load stays at or below 10 points; unavailable technicians are never picked.",
    "BR-07": "SLA pauses ON_HOLD; response met at first acknowledgement; breach is now > deadline.",
    "BR-08": "Unacknowledged P1/P2 escalate one level per elapsed response target.",
    "BR-09": "Duplicates are suggested, linked, and near-identical repeats refused.",
    "BR-10": "Audit records are append-only and hash-chained; incidents are never deleted.",
}


class CaseFileError(ValueError):
    """cases.yaml is malformed or names a test that does not exist."""


class RunError(RuntimeError):
    """A suite did not finish, so there are no results to report."""


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    title: str
    requirements: tuple[str, ...]
    preconditions: str
    steps: str
    input: str
    expected: str
    tests: tuple[str, ...]


@dataclass(frozen=True)
class CaseResult:
    case: Case
    matched: tuple[str, ...]
    passed: int
    failed: int
    skipped: int

    @property
    def status(self) -> str:
        if not self.matched or self.failed or self.passed == 0:
            return "FAIL"
        return "PASS"

    @property
    def actual(self) -> str:
        if not self.matched:
            return "No such test was run."
        functions = len(self.case.tests)
        runs = len(self.matched)
        noun = "check" if runs == 1 else "checks"
        text = f"{self.passed} of {runs} automated {noun} passed"
        if runs > functions:
            text += f" ({functions} tests, {runs} with their parametrised cases)"
        if self.failed:
            text += f"; {self.failed} failed"
        if self.skipped:
            text += f"; {self.skipped} skipped"
        return text + "."


def load_cases(path: Path = CASES) -> list[Case]:
    """Read and check the documented cases."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = raw.get("cases") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise CaseFileError("cases.yaml must hold a `cases:` list")
    cases: list[Case] = []
    for entry in entries:
        try:
            case = Case(
                id=str(entry["id"]),
                category=str(entry["category"]),
                title=str(entry["title"]),
                requirements=tuple(str(r) for r in entry["requirements"]),
                preconditions=str(entry["preconditions"]),
                steps=str(entry["steps"]),
                input=str(entry["input"]),
                expected=str(entry["expected"]),
                tests=tuple(str(t) for t in entry["tests"]),
            )
        except (KeyError, TypeError) as error:
            raise CaseFileError(f"case {entry!r} is missing {error}") from None
        if case.category not in CATEGORIES:
            raise CaseFileError(f"{case.id}: unknown category {case.category!r}")
        if not case.tests:
            raise CaseFileError(f"{case.id}: names no test")
        cases.append(case)
    ids = [c.id for c in cases]
    duplicates = sorted(i for i, n in Counter(ids).items() if n > 1)
    if duplicates:
        raise CaseFileError(f"duplicate case ids: {duplicates}")
    if len(cases) < MIN_CASES:
        raise CaseFileError(f"only {len(cases)} cases; the requirements ask for {MIN_CASES}")
    missing = sorted(set(CATEGORIES) - {c.category for c in cases})
    if missing:
        raise CaseFileError(f"no case in categories {missing}")
    return cases


def matching(test_id: str, outcomes: dict[str, dict[str, Any]]) -> list[str]:
    """The run's node ids for a test id; without ``[...]`` it covers every parametrisation."""
    if "[" in test_id:
        return [test_id] if test_id in outcomes else []
    return [n for n in outcomes if n == test_id or n.startswith(test_id + "[")]


def evaluate(cases: list[Case], outcomes: dict[str, dict[str, Any]]) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        matched: list[str] = []
        for test_id in case.tests:
            found = matching(test_id, outcomes)
            if not found:
                raise CaseFileError(f"{case.id}: {test_id} was not collected")
            matched.extend(found)
        counts = Counter(outcomes[n]["outcome"] for n in matched)
        results.append(
            CaseResult(
                case,
                tuple(matched),
                passed=counts["passed"],
                failed=counts["failed"] + counts["error"] + counts["not run"],
                skipped=counts["skipped"],
            )
        )
    return results


# --------------------------------------------------------------------------- running


def _git_commit() -> str:
    git = shutil.which("git")
    if git is None:
        return "unknown"
    out = subprocess.run(  # noqa: S603 - fixed arguments
        [git, "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
    )
    return out.stdout.strip() or "unknown"


def run_tests() -> dict[str, Any]:
    """Run the backend and frontend suites; return the raw results."""
    RUN_DIR.mkdir(exist_ok=True)
    results_json = RUN_DIR / "pytest.json"
    coverage_json = RUN_DIR / "coverage.json"
    # A previous run's files must never pass for this run's results.
    for stale in (results_json, coverage_json, RUN_DIR / "vitest.json", RUN_DIR / "run.json"):
        stale.unlink(missing_ok=True)
    clock = SystemClock()  # when the run happened, for the record only
    started = clock.now()
    pytest_run = subprocess.run(  # noqa: S603 - fixed arguments
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "scripts.pytest_results",
            f"--results-json={results_json}",
            "--cov",
            f"--cov-report=json:{coverage_json}",
            "-q",
        ],
        cwd=BACKEND,
        check=False,  # a failing test is a result to report, not a reason to stop
    )
    finished = clock.now()
    # 0: all passed, 1: some failed. Anything else (interrupted, collection or usage error)
    # means the suite did not run to the end.
    if pytest_run.returncode not in (0, 1) or not results_json.exists():
        msg = f"pytest did not finish (exit code {pytest_run.returncode}); nothing to report"
        raise RunError(msg)
    if not coverage_json.exists():
        raise RunError("pytest wrote no coverage report; nothing to report")
    vitest = _run_vitest()
    pytest_data = json.loads(results_json.read_text(encoding="utf-8"))
    coverage = json.loads(coverage_json.read_text(encoding="utf-8"))["totals"]
    raw = {
        "started": started.strftime("%Y-%m-%d %H:%M"),
        "seconds": round((finished - started).total_seconds()),
        "commit": _git_commit(),
        "python": sys.version.split()[0],
        "database": _database_name(),
        "tests": pytest_data["tests"],
        "coverage_percent": round(coverage["percent_covered"], 1),
        "vitest": vitest,
    }
    (RUN_DIR / "run.json").write_text(json.dumps(raw, indent=1), encoding="utf-8")
    return raw


def _database_name() -> str:
    """The database the backend suite ran on (tests/conftest.py reads TEST_DATABASE_URL)."""
    url = os.environ.get("TEST_DATABASE_URL", "")
    return "PostgreSQL" if url.startswith("postgres") else "SQLite"


def _run_vitest() -> dict[str, int] | None:
    """Vitest's totals; None only when the frontend is not installed (it is then not run)."""
    npx = shutil.which("npx")
    frontend = REPO / "frontend"
    if npx is None or not (frontend / "node_modules").exists():
        print("test_report: frontend not installed; Vitest not run")
        return None
    out = RUN_DIR / "vitest.json"
    subprocess.run(  # noqa: S603 - fixed arguments
        [npx, "vitest", "run", "--reporter=json", f"--outputFile={out}"],
        cwd=frontend,
        check=False,
        capture_output=True,
    )
    if not out.exists():
        raise RunError("Vitest did not finish; nothing to report")
    data = json.loads(out.read_text(encoding="utf-8"))
    return {
        "total": int(data["numTotalTests"]),
        "passed": int(data["numPassedTests"]),
        "failed": int(data["numFailedTests"]),
        "files": len(data.get("testResults", [])),
    }


# --------------------------------------------------------------------------- rendering

_TEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_TEX_TEXT = {"≥": r"$\geq$", "≤": r"$\leq$", "→": r"$\rightarrow$", "×": r"$\times$", "µ": r"$\mu$"}


def tex(text: str) -> str:
    """Escape plain text for LaTeX."""
    out = "".join(_TEX_SPECIAL.get(ch, ch) for ch in text)
    for char, replacement in _TEX_TEXT.items():
        out = out.replace(char, replacement)
    return out.replace(" x ", r" $\times$ ")


def tt(text: str) -> str:
    """A test id in typewriter type, breakable after its separators."""
    escaped = tex(text).replace("/", r"/\allowbreak{}").replace("::", r"::\allowbreak{}")
    return r"\texttt{\footnotesize " + escaped.replace(r"\_", r"\_\allowbreak{}") + "}"


@dataclass(frozen=True)
class Totals:
    total: int
    passed: int
    failed: int
    skipped: int


def totals(tests: dict[str, dict[str, Any]]) -> Totals:
    counts = Counter(t["outcome"] for t in tests.values())
    failed = counts["failed"] + counts["error"] + counts["not run"]
    return Totals(len(tests), counts["passed"], failed, counts["skipped"])


def rule_rows(tests: dict[str, dict[str, Any]]) -> list[tuple[str, int, int, list[str]]]:
    """Per business rule: tests claiming it, how many passed, and the files they live in."""
    rows = []
    for rule in BUSINESS_RULES:
        ids = [n for n, t in tests.items() if rule in t["reqs"]]
        passed = sum(1 for n in ids if tests[n]["outcome"] == "passed")
        files = sorted({n.split("::")[0].rsplit("/", 1)[-1].removesuffix(".py") for n in ids})
        rows.append((rule, len(ids), passed, files))
    return rows


def cases_tex(results: list[CaseResult]) -> str:
    lines = [
        "% GENERATED by backend/scripts/test_report.py from docs/testing/cases.yaml and a real",
        "% test run. Do not edit: change cases.yaml and run `make test-report`.",
    ]
    for r in results:
        c = r.case
        colour = "green!45!black" if r.status == "PASS" else "red!70!black"
        lines += [
            r"\begin{testcase}{" + tex(c.id) + "}{" + tex(c.title) + "}",
            r"Category & " + tex(CATEGORIES[c.category]) + r" \\",
            r"Requirements & " + tex(", ".join(c.requirements)) + r" \\",
            r"Preconditions & " + tex(c.preconditions) + r" \\",
            r"Steps & " + tex(c.steps) + r" \\",
            r"Input & " + tex(c.input) + r" \\",
            r"Expected & " + tex(c.expected) + r" \\",
            r"Actual & " + tex(r.actual) + r" \\",
            r"Status & \textbf{\textcolor{" + colour + "}{" + r.status + r"}} \\",
            r"Automated by & " + r" \newline ".join(tt(t) for t in c.tests) + r" \\",
            r"\end{testcase}",
            "",
        ]
    return "\n".join(lines)


#: What each backend test folder checks (blueprint §13).
SUITES = {
    "unit/domain": "Domain rules: states, priority, SLA, assignment, escalation, similarity",
    "unit/services": "Services on in-memory repositories: facade, monitor, notifications, auth",
    "unit/adapters": "Gemini, SMTP, Telegram and Google adapters against fake transports",
    "unit/core": "Clocks, security",
    "unit/scripts": "The report's generators",
    "unit": "Configuration",
    "contract": "One repository contract run on memory and SQLite (and PostgreSQL in CI)",
    "integration": "HTTP API, authorisation matrix, SQL repositories, migrations, seed",
}


def suite_of(node_id: str) -> str:
    parts = node_id.split("::")[0].split("/")[1:-1]  # drop "tests" and the file name
    return "/".join(parts[:2]) if parts else "unit"


def suite_rows(tests: dict[str, dict[str, Any]]) -> list[tuple[str, int, int]]:
    count = Counter(suite_of(n) for n in tests)
    passed = Counter(suite_of(n) for n, t in tests.items() if t["outcome"] == "passed")
    return [(s, count[s], passed[s]) for s in SUITES if count[s]]


def summary_tex(raw: dict[str, Any], results: list[CaseResult]) -> str:
    t = totals(raw["tests"])
    passed_cases = sum(1 for r in results if r.status == "PASS")
    by_category = Counter(r.case.category for r in results)
    vitest = raw.get("vitest")
    rows = [
        (
            "Backend tests (pytest)",
            f"{t.total} run: {t.passed} passed, {t.failed} failed, {t.skipped} skipped",
        ),
        ("Backend line and branch coverage", f"{raw['coverage_percent']} %"),
    ]
    if vitest:
        rows.append(
            (
                "Frontend tests (Vitest)",
                f"{vitest['total']} in {vitest['files']} files: {vitest['passed']} passed, "
                f"{vitest['failed']} failed",
            )
        )
    rows += [
        ("Documented cases", f"{len(results)}: {passed_cases} PASS"),
        (
            "Cases per category",
            ", ".join(f"{CATEGORIES[k].lower()} {by_category[k]}" for k in CATEGORIES),
        ),
        (
            "Run",
            f"{raw['started']} UTC, {raw['seconds']} s, commit {raw['commit']}, "
            f"Python {raw['python']}, {raw.get('database', 'SQLite')}",
        ),
    ]
    body = "\n".join(tex(k) + " & " + tex(v) + r" \\" for k, v in rows)
    suites = "\n".join(
        r"\texttt{\small tests/"
        + tex(name).replace("/", r"/\allowbreak{}")
        + "} & "
        + tex(SUITES[name])
        + f" & {count} & {passed} "
        + r"\\"
        for name, count, passed in suite_rows(raw["tests"])
    )
    return "\n".join(
        [
            "% GENERATED by backend/scripts/test_report.py from a real test run. Do not edit.",
            r"\noindent\begin{tabularx}{\textwidth}{@{}lX@{}}",
            r"\toprule",
            body,
            r"\bottomrule",
            r"\end{tabularx}",
            "",
            r"\medskip\noindent\begin{tabularx}{\textwidth}"
            r"{@{}>{\raggedright\arraybackslash}p{3.4cm}Xrr@{}}",
            r"\toprule",
            r"Suite & What it checks & Tests & Passed \\",
            r"\midrule",
            suites,
            r"\bottomrule",
            r"\end{tabularx}",
            "",
        ]
    )


def traceability_tex(raw: dict[str, Any], results: list[CaseResult]) -> str:
    cases_for: dict[str, list[str]] = {}
    for r in results:
        for req in r.case.requirements:
            cases_for.setdefault(req, []).append(r.case.id)
    lines = [
        "% GENERATED by backend/scripts/test_report.py from a real test run. Do not edit.",
        r"\begin{longtable}{@{}p{1.3cm}>{\raggedright\arraybackslash}p{4.6cm}rr"
        r">{\raggedright\arraybackslash}p{2.1cm}>{\raggedright\arraybackslash}p{4.2cm}@{}}",
        r"\toprule",
        r"Rule & Statement & Tests & Passed & Cases & Test files \\",
        r"\midrule",
        r"\endhead",
    ]
    for rule, count, passed, files in rule_rows(raw["tests"]):
        file_list = ", ".join(tt(f) for f in files)
        lines.append(
            f"{rule} & {tex(BUSINESS_RULES[rule])} & {count} & {passed} & "
            f"{tex(', '.join(cases_for.get(rule, [])))} & {file_list} " + r"\\"
        )
    lines += [r"\bottomrule", r"\end{longtable}", ""]
    return "\n".join(lines)


def markdown(raw: dict[str, Any], results: list[CaseResult]) -> str:
    t = totals(raw["tests"])
    vitest = raw.get("vitest")
    out = [
        "# Test report",
        "",
        "Generated by `make test-report` (`backend/scripts/test_report.py`) from a real run;",
        "do not edit. The cases themselves live in [cases.yaml](cases.yaml).",
        "",
        f"- Run: {raw['started']} UTC, {raw['seconds']} s, commit `{raw['commit']}`, "
        f"Python {raw['python']}, {raw.get('database', 'SQLite')}",
        f"- Backend: {t.total} tests, {t.passed} passed, {t.failed} failed, "
        f"{t.skipped} skipped; coverage {raw['coverage_percent']} %",
    ]
    if vitest:
        out.append(
            f"- Frontend: {vitest['total']} Vitest tests, {vitest['passed']} passed, "
            f"{vitest['failed']} failed"
        )
    out += [
        f"- Documented cases: {len(results)}, {sum(1 for r in results if r.status == 'PASS')} PASS",
        "",
        "## Documented cases",
        "",
        "| ID | Category | Case | Requirements | Actual | Status |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        c = r.case
        out.append(
            f"| {c.id} | {CATEGORIES[c.category]} | {c.title} | {', '.join(c.requirements)} "
            f"| {r.actual} | **{r.status}** |"
        )
    out += [
        "",
        "## Business rules to tests",
        "",
        "| Rule | Statement | Tests | Passed |",
        "|---|---|---|---|",
    ]
    for rule, count, passed, _ in rule_rows(raw["tests"]):
        out.append(f"| {rule} | {BUSINESS_RULES[rule]} | {count} | {passed} |")
    return "\n".join(out) + "\n"


def write_outputs(raw: dict[str, Any], results: list[CaseResult]) -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    outputs = {
        GENERATED / "test-cases.tex": cases_tex(results),
        GENERATED / "test-summary.tex": summary_tex(raw, results),
        GENERATED / "traceability.tex": traceability_tex(raw, results),
        MARKDOWN: markdown(raw, results),
    }
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"test_report: wrote {path.relative_to(REPO)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-run", action="store_true", help="reuse the last run's results")
    args = parser.parse_args(argv)
    cases = load_cases()
    try:
        if args.skip_run:
            raw = json.loads((RUN_DIR / "run.json").read_text(encoding="utf-8"))
        else:
            raw = run_tests()
    except (RunError, FileNotFoundError) as error:
        print(f"test_report: {error}", file=sys.stderr)
        return 2
    results = evaluate(cases, raw["tests"])
    write_outputs(raw, results)
    failing = [r.case.id for r in results if r.status != "PASS"]
    t = totals(raw["tests"])
    print(
        f"test_report: {len(results)} cases, failing: {failing or 'none'}; "
        f"{t.passed}/{t.total} backend tests passed"
    )
    vitest_failed = bool(raw.get("vitest") and raw["vitest"]["failed"])
    return 1 if failing or t.failed or vitest_failed else 0


if __name__ == "__main__":
    sys.exit(main())
