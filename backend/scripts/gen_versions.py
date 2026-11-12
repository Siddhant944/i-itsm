"""Write the report's technology tables with versions read from the lock files (P6.2).

Versions come from ``backend/uv.lock``, ``frontend/package-lock.json`` and
``e2e/package-lock.json``, so chapter 5 always states what the code is really built with.
Rows that are not packages (databases, services, images) give their version here, next to
the file that pins it. Output: ``report/generated/versions.tex``.

Usage: ``uv run python scripts/gen_versions.py``.
"""

from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "report" / "generated" / "versions.tex"


@cache
def _uv_versions() -> dict[str, str]:
    lock = tomllib.loads((REPO / "backend" / "uv.lock").read_text(encoding="utf-8"))
    return {p["name"]: p["version"] for p in lock["package"] if "version" in p}


@cache
def _npm_versions(folder: str) -> dict[str, str]:
    lock: dict[str, Any] = json.loads(
        (REPO / folder / "package-lock.json").read_text(encoding="utf-8")
    )
    return {
        path.removeprefix("node_modules/"): meta["version"]
        for path, meta in lock["packages"].items()
        if path.startswith("node_modules/") and "version" in meta
    }


def _short(version: str) -> str:
    """Major.minor, which is what the text discusses; patch levels churn."""
    return ".".join(version.split(".")[:2])


@dataclass(frozen=True)
class Row:
    name: str
    packages: tuple[str, ...]  # "py:x", "npm:x", "e2e:x" or a literal version
    purpose: str

    def version(self) -> str:
        found = []
        for ref in self.packages:
            source, _, package = ref.partition(":")
            if source == "py":
                found.append(_short(_uv_versions()[package]))
            elif source == "npm":
                found.append(_short(_npm_versions("frontend")[package]))
            elif source == "e2e":
                found.append(_short(_npm_versions("e2e")[package]))
            else:
                found.append(ref)
        return ", ".join(found)


SECTIONS: tuple[tuple[str, tuple[Row, ...]], ...] = (
    (
        "Backend (Python)",
        (
            Row("Python", ("3.12",), "Language of the domain, services and API (.python-version)."),
            Row("FastAPI", ("py:fastapi",), "HTTP API, dependency injection, OpenAPI, WebSockets."),
            Row("Starlette", ("py:starlette",), "ASGI toolkit under FastAPI (middleware, CORS)."),
            Row("Uvicorn", ("py:uvicorn",), "ASGI server."),
            Row("Pydantic", ("py:pydantic",), "Validation of every request and response."),
            Row(
                "pydantic-settings",
                ("py:pydantic-settings",),
                "Typed configuration from the environment.",
            ),
            Row("SQLAlchemy", ("py:sqlalchemy",), "ORM behind the repository interfaces."),
            Row("Alembic", ("py:alembic",), "Database migrations, run on every deploy."),
            Row("psycopg", ("py:psycopg",), "PostgreSQL driver."),
            Row(
                "APScheduler",
                ("py:apscheduler",),
                "In-process SLA monitor every 30 s of clock time.",
            ),
            Row(
                "argon2-cffi, PyJWT",
                ("py:argon2-cffi", "py:pyjwt"),
                "Password hashing; signed access tokens; Google ID-token checks.",
            ),
            Row("email-validator", ("py:email-validator",), "Email address validation."),
            Row(
                "Google Gen AI SDK",
                ("py:google-genai",),
                "Gemini classification, grounded summaries and embeddings.",
            ),
            Row(
                "httpx", ("py:httpx",), "HTTP client for Telegram and Google keys; API test client."
            ),
        ),
    ),
    (
        "Frontend (TypeScript)",
        (
            Row("Node.js", ("22 LTS",), "Build and test runtime (frontend/Dockerfile)."),
            Row("TypeScript", ("npm:typescript",), "Static typing in strict mode."),
            Row("React", ("npm:react",), "Component UI for the three portals."),
            Row("React Router", ("npm:react-router",), "Role-based routing and navigation."),
            Row(
                "TanStack Query",
                ("npm:@tanstack/react-query",),
                "Server state: caching, loading and error states.",
            ),
            Row(
                "openapi-typescript, openapi-fetch",
                ("npm:openapi-typescript", "npm:openapi-fetch"),
                "Typed API client generated from the OpenAPI document.",
            ),
            Row("Vite", ("npm:vite",), "Development server and production build."),
            Row("Tailwind CSS", ("npm:tailwindcss",), "Styling and the three portal themes."),
            Row("Recharts", ("npm:recharts",), "Dashboard charts."),
        ),
    ),
    (
        "Data, services and infrastructure",
        (
            Row("SQLite", ("3",), "Local development and tests (foreign_keys=ON, WAL)."),
            Row("PostgreSQL", ("16",), "Docker Compose and deployment; CI runs every test on it."),
            Row(
                "Google Gemini API",
                ("REST",),
                "AI classification, summaries, embeddings; rule and TF-IDF fallbacks.",
            ),
            Row("SMTP email", ("--",), "Email notifications (console fallback when unset)."),
            Row("Telegram Bot API", ("REST",), "P1/P2, SLA and escalation alerts."),
            Row("Google Identity Services", ("--",), "Sign-in restricted to the campus domain."),
            Row("Docker, Docker Compose", ("29",), "One-command start of API, web and PostgreSQL."),
            Row("nginx", ("1.29",), "Serves the built frontend and proxies /api in Docker."),
            Row(
                "Render, Neon",
                ("free plans",),
                "Cloud hosting: API container, static web, PostgreSQL.",
            ),
            Row("GitHub, GitHub Actions", ("--",), "Version control, issues as the bug log, CI."),
        ),
    ),
    (
        "Quality and documentation tooling",
        (
            Row(
                "pytest, pytest-cov",
                ("py:pytest", "py:pytest-cov"),
                "Backend unit, contract and integration tests with coverage.",
            ),
            Row("Ruff", ("py:ruff",), "Linting (incl. a ban on wall-clock calls) and formatting."),
            Row("mypy", ("py:mypy",), "Static type checking in --strict mode."),
            Row("import-linter", ("py:import-linter",), "Machine-checked layer rules."),
            Row(
                "ESLint, Prettier",
                ("npm:eslint", "npm:prettier"),
                "TypeScript linting and formatting.",
            ),
            Row(
                "Vitest, Testing Library",
                ("npm:vitest", "npm:@testing-library/react"),
                "Frontend component tests.",
            ),
            Row(
                "Playwright, axe-core",
                ("e2e:@playwright/test", "e2e:@axe-core/playwright"),
                "End-to-end workflows and accessibility checks.",
            ),
            Row(
                "pre-commit, gitleaks",
                ("py:pre-commit", "8.30"),
                "Commit-time checks, including secret scanning.",
            ),
            Row(
                "tectonic, PlantUML",
                ("0.17", "1.2026.9"),
                "This report and its diagrams, built from sources.",
            ),
        ),
    ),
)

_TEX = {"&": r"\&", "%": r"\%", "_": r"\_", "#": r"\#", "$": r"\$"}


def tex(text: str) -> str:
    return "".join(_TEX.get(ch, ch) for ch in text)


def render() -> str:
    lines = [
        "% GENERATED by backend/scripts/gen_versions.py from uv.lock and package-lock.json.",
        "% Do not edit: change a dependency and run `make report`.",
    ]
    for title, rows in SECTIONS:
        lines += [
            r"\subsection*{" + tex(title) + "}",
            r"\begin{longtable}{@{}>{\raggedright\arraybackslash}p{3.8cm}"
            r">{\raggedright\arraybackslash}p{2.2cm}>{\raggedright\arraybackslash}p{9.4cm}@{}}",
            r"\toprule",
            r"\textbf{Technology} & \textbf{Version} & \textbf{Purpose} \\",
            r"\midrule",
            r"\endhead",
        ]
        lines += [f"{tex(r.name)} & {tex(r.version())} & {tex(r.purpose)} " + r"\\" for r in rows]
        lines += [r"\bottomrule", r"\end{longtable}", ""]
    return "\n".join(lines)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(), encoding="utf-8", newline="\n")
    print(f"gen_versions: wrote {out}")


if __name__ == "__main__":
    main()
