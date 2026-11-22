"""Assemble ``deliverables/``: one numbered folder per item of the brief's Deliverables list.

The brief (docs/source/OOP_S1_2026-2027_Project.pdf, "Deliverables") asks for nine items. Each
folder holds the matching report chapter as its own PDF, cut from the built report, plus the
rendered diagrams and data files for that item, renamed for an evaluator; ``README.md`` maps
every item to its files and to their sources in the repository (D-045).

Needs the built report (``make report``), the rendered diagrams (``make diagrams``) and the
tools ``pdfinfo`` and ``pdftotext`` (poppler) and ``qpdf``, which keeps one copy of each font
when it cuts a chapter out.

Usage: ``uv run python scripts/build_deliverables.py``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.repositories.sqlalchemy.models import Base

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "deliverables"
REPORT_PDF = REPO / "report" / "build" / "main.pdf"
DIAGRAMS = REPO / "docs" / "diagrams"
SUBMISSION = "15_OOP_S1_2026-2027_Project"
REPO_URL = "https://github.com/Siddhant944/i-itsm"


@dataclass(frozen=True)
class Asset:
    """A file copied into a deliverable folder under an evaluator-friendly name."""

    source: Path
    name: str  # published name without extension; the source's extension is kept


@dataclass(frozen=True)
class Deliverable:
    """One numbered item of the brief's Deliverables list and where it lives."""

    folder: str
    title: str
    chapter: str  # the report chapter's title, as printed after "Chapter N"
    assets: tuple[Asset, ...] = ()
    note: str = ""


def _diagram(path: str, name: str) -> tuple[Asset, ...]:
    """The SVG (sharp, small) and the PNG (opens anywhere) of one rendered diagram."""
    return tuple(Asset(DIAGRAMS / f"{path}.{ext}", name) for ext in ("svg", "png"))


DELIVERABLES: tuple[Deliverable, ...] = (
    Deliverable(
        "01_Problem_Analysis",
        "Problem Analysis",
        "Problem Analysis",
        note="Problem, stakeholders, existing challenges, proposed solution, assumptions.",
    ),
    Deliverable(
        "02_Requirements_Specification",
        "Requirements Specification",
        "Requirements Specification",
        note="Functional and non-functional requirements, user roles, business rules "
        "BR-01 to BR-10.",
    ),
    Deliverable(
        "03_System_Architecture",
        "System Architecture",
        "System Architecture",
        _diagram("architecture", "3.1_Architecture_Diagram")
        + _diagram("deployment", "3.2_Deployment_Diagram"),
        note="Layers and components with their interactions, the request flow, cross-cutting "
        "concerns and the deployment.",
    ),
    Deliverable(
        "04_UML_Diagrams",
        "UML Diagrams",
        "UML Diagrams",
        _diagram("usecase", "4.01_Use_Case_Diagram")
        + _diagram("generated/class-users", "4.02_Class_Diagram_Users_and_Permissions")
        + _diagram("generated/class-incident", "4.03_Class_Diagram_Incident_Aggregate")
        + _diagram("generated/class-states", "4.04_Class_Diagram_State_Pattern")
        + _diagram("generated/class-strategies", "4.05_Class_Diagram_Priority_and_Assignment")
        + _diagram("generated/class-sla", "4.06_Class_Diagram_SLA_Risk_and_Escalation")
        + _diagram("generated/class-ports", "4.07_Class_Diagram_Ports_and_Adapters")
        + _diagram("generated/state", "4.08_State_Diagram_Incident_Lifecycle")
        + _diagram("sequence-wf1", "4.09_Sequence_Diagram_Workflow_1")
        + _diagram("sequence-wf2", "4.10_Sequence_Diagram_Workflow_2")
        + _diagram("sequence-wf3", "4.11_Sequence_Diagram_Workflow_3"),
        note="Use case, six class diagrams (classes, attributes, methods, interfaces, "
        "inheritance, associations, composition and aggregation), the lifecycle state diagram "
        "and one sequence diagram per demonstrated workflow.",
    ),
    Deliverable(
        "05_Technology_Stack",
        "Technology Stack",
        "Technology Stack",
        note="Every technology, framework, library and service, with the versions the code is "
        "built with.",
    ),
    Deliverable(
        "06_Source_Code",
        "Source Code",
        "Source Code Repository",
        note=f"Repository: {REPO_URL}. Layout, build commands, CI and conventions.",
    ),
    Deliverable(
        "07_Database_Design",
        "Database Design",
        "Database Design",
        _diagram("generated/er", "7.1_ER_Diagram"),
        note="ER diagram, schema (also as PostgreSQL DDL), important relationships, sample data.",
    ),
    Deliverable(
        "08_Testing",
        "Testing",
        "Testing",
        (
            Asset(REPO / "docs" / "testing" / "test-report.md", "8.1_Test_Report"),
            Asset(REPO / "docs" / "testing" / "cases.yaml", "8.2_Documented_Test_Cases"),
            Asset(
                REPO / "docs" / "testing" / "duplicates.md", "8.3_Duplicate_Detection_Evaluation"
            ),
        ),
        note="24 documented test cases (normal, boundary, invalid input, exception, "
        "authorisation, business rules), all passing, and the full automated suite's results.",
    ),
    Deliverable(
        "09_Project_Demonstration",
        "Project Demonstration",
        "Project Demonstration",
        (
            Asset(REPO / "docs" / "VIDEO_SCRIPT.pdf", "9.1_Video_Script"),
            *(
                Asset(p, f"screenshots/{p.stem}")
                for p in sorted((REPO / "docs" / "screenshots").glob("*.jpg"))
            ),
        ),
        note=f"The video (16 min) is uploaded to the course's shared folder as {SUBMISSION}. "
        "The chapter times each part and maps the three workflows to the brief's steps.",
    ),
)

#: Report chapters that answer no single numbered item but belong with the submission.
SUPPLEMENTARY: tuple[tuple[str, str], ...] = (
    ("Security Considerations", "S1_Security_Considerations"),
    ("OOP Concepts and Design Patterns", "S2_OOP_Concepts_and_Design_Patterns"),
    ("Traceability Matrix", "S3_Traceability_Matrix"),
    ("Team Responsibilities and Use of AI Tools", "S4_Team_Responsibilities_and_AI_Use"),
)


def _run(*cmd: str) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout  # noqa: S603 (fixed tool names)


def chapter_pages(pdf: Path) -> dict[str, tuple[int, int]]:
    """Map each chapter's title to its first and last page (1-based, inclusive)."""
    pages = int(re.search(r"Pages:\s+(\d+)", _run("pdfinfo", str(pdf)))[1])  # type: ignore[index]
    starts: list[tuple[str, int]] = []
    for page in range(1, pages + 1):
        lines = [
            line.strip()
            for line in _run(
                "pdftotext", "-f", str(page), "-l", str(page), str(pdf), "-"
            ).splitlines()
            if line.strip()
        ]
        if len(lines) >= 2 and re.fullmatch(r"Chapter \d+", lines[0]):
            starts.append((lines[1], page))
    bounds: dict[str, tuple[int, int]] = {}
    for i, (title, first) in enumerate(starts):
        last = starts[i + 1][1] - 1 if i + 1 < len(starts) else pages
        bounds[title] = (first, last)
    return bounds


def _find(bounds: dict[str, tuple[int, int]], title: str) -> tuple[int, int] | None:
    """A chapter's pages; a long title may wrap onto a second line in the PDF."""
    for printed, pages in bounds.items():
        if title.startswith(printed) or printed.startswith(title):
            return pages
    return None


def cut(pdf: Path, pages: tuple[int, int], out: Path) -> None:
    """Write pages ``first..last`` of ``pdf`` to ``out``."""
    first, last = pages
    _run("qpdf", str(pdf), "--pages", ".", f"{first}-{last}", "--", str(out))


def schema_sql() -> str:
    """The database schema as PostgreSQL DDL, from the same ORM metadata Alembic migrates."""
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    statements = ["-- I-ITSM database schema (PostgreSQL), generated from the ORM metadata.\n"]
    for table in Base.metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";\n")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";\n")
    return "\n".join(statements)


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def build() -> list[str]:
    """Rebuild ``deliverables/`` and return the README's lines."""
    if not REPORT_PDF.exists():
        sys.exit(f"build_deliverables: {_rel(REPORT_PDF)} is missing; run `make report` first")
    bounds = chapter_pages(REPORT_PDF)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    report_name = f"{SUBMISSION}_Report.pdf"
    shutil.copyfile(REPORT_PDF, OUT / report_name)

    readme = [
        "# Deliverables: I-ITSM, Group 15",
        "",
        "CS F213 / MAC F212 Object-Oriented Programming, Semester I 2026-27. Members: Tushar B,",
        "Siddhant L Pathak, Shri Krishna P, Ishaan S.",
        "",
        "One numbered folder per item of the brief's *Deliverables* list. Each holds that item's",
        "report chapter as its own PDF and the files that go with it. Generated by",
        "`make deliverables` from the report and the diagrams; do not edit by hand.",
        "",
        f"- **Full report (one PDF per group):** [{report_name}]({report_name})",
        f"- **Demonstration video:** `{SUBMISSION}`, in the course's shared folder",
        f"- **Source code:** {REPO_URL}",
        "",
        "| # | Deliverable | Files | Report chapter | Source in the repository |",
        "|---|---|---|---|---|",
    ]
    for number, item in enumerate(DELIVERABLES, start=1):
        folder = OUT / item.folder
        folder.mkdir()
        files: list[str] = []
        pages = _find(bounds, item.chapter)
        if pages is not None:
            name = f"{item.folder}.pdf"
            cut(REPORT_PDF, pages, folder / name)
            files.append(f"[{name}]({item.folder}/{name})")
        for asset in item.assets:
            target = folder / f"{asset.name}{asset.source.suffix}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(asset.source, target)
            if "/" not in asset.name and asset.source.suffix != ".png":
                files.append(f"[{target.name}]({item.folder}/{target.name})")
        if number == 7:
            (folder / "7.2_Database_Schema.sql").write_text(schema_sql(), encoding="utf-8")
            files.append(f"[7.2_Database_Schema.sql]({item.folder}/7.2_Database_Schema.sql)")
        if any("/" in a.name for a in item.assets):
            files.append(f"[screenshots/]({item.folder}/screenshots)")
        sources = sorted({"report/chapters"} | {_rel(a.source.parent) for a in item.assets})
        chapter = f"pp. {pages[0]}-{pages[1]}" if pages else "—"
        readme.append(
            f"| {number} | **{item.title}**<br>{item.note} | {'<br>'.join(files)} | {chapter} | "
            f"{', '.join(f'`{s}/`' for s in sources)} |"
        )

    supplementary = OUT / "10_Supplementary"
    supplementary.mkdir()
    readme += ["", "## Supplementary chapters", ""]
    for title, name in SUPPLEMENTARY:
        pages = _find(bounds, title)
        if pages is not None:
            cut(REPORT_PDF, pages, supplementary / f"{name}.pdf")
            readme.append(
                f"- [{name}.pdf](10_Supplementary/{name}.pdf): {title} (pp. {pages[0]}-{pages[1]})"
            )
    readme += [
        "",
        "Diagrams come as SVG (sharp at any zoom, opens in a browser) and PNG (opens anywhere).",
        "To rebuild this folder: `make report`, then `make deliverables`.",
        "",
    ]
    return readme


def main() -> None:
    readme = build()
    (OUT / "README.md").write_text("\n".join(readme), encoding="utf-8")
    print(f"deliverables: {_rel(OUT)}")


if __name__ == "__main__":
    main()
