# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Cross-platform task runner for I-ITSM (Linux, macOS and Windows; no make or Docker needed).

Usage: ``uv run scripts/dev.py <command>`` from the repository root;
``make <command>`` delegates here.
Run ``uv run scripts/dev.py --help`` for the command list.
"""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"
E2E = REPO / "e2e"
REPORT = REPO / "report"
DIAGRAMS = REPO / "docs" / "diagrams"
OPENAPI_JSON = FRONTEND / "src" / "api" / "openapi.json"
SCHEMA_TS = FRONTEND / "src" / "api" / "schema.d.ts"


class TaskError(Exception):
    """A step failed; the message says which."""


def exe(name: str) -> str:
    """Resolve an executable on PATH (handles npm.cmd and friends on Windows)."""
    found = shutil.which(name)
    if found is None:
        raise TaskError(f"'{name}' is not on PATH; see the README's setup section")
    return found


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for child processes, without this script's own (ephemeral) virtualenv."""
    env = {**os.environ, **(extra or {})}
    env.pop("VIRTUAL_ENV", None)
    return env


def run(cmd: Sequence[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    """Run one command, echoing it first; raise TaskError on a non-zero exit."""
    rel = cwd.relative_to(REPO) if cwd != REPO else Path(".")
    print(f"\n$ ({rel}) {' '.join(cmd)}", flush=True)
    result = subprocess.run([exe(cmd[0]), *cmd[1:]], cwd=cwd, env=child_env(env), check=False)  # noqa: S603
    if result.returncode != 0:
        raise TaskError(f"failed ({result.returncode}): {' '.join(cmd)}")


def npm_install(cwd: Path) -> None:
    run(["npm", "ci" if (cwd / "package-lock.json").exists() else "install"], cwd)


# ------------------------------------------------------------------ commands


def setup(_: argparse.Namespace) -> None:
    """Install backend, frontend and e2e dependencies and the git hooks."""
    run(["uv", "sync"], BACKEND)
    npm_install(FRONTEND)
    npm_install(E2E)
    if (REPO / ".git").exists():
        run(["uv", "run", "pre-commit", "install"], BACKEND)


def dev(_: argparse.Namespace) -> None:
    """Run the API (http://127.0.0.1:8000) and the web app (http://localhost:5173) with reload."""
    procs = [
        subprocess.Popen(  # noqa: S603
            [
                exe("uv"),
                "run",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--reload",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=BACKEND,
            env=child_env(),
        ),
        subprocess.Popen([exe("npm"), "run", "dev"], cwd=FRONTEND, env=child_env()),  # noqa: S603
    ]
    print("API http://127.0.0.1:8000/health · web http://localhost:5173 · Ctrl+C stops both")
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                if os.name == "nt":
                    p.terminate()
                else:
                    p.send_signal(signal.SIGINT)
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def test(_: argparse.Namespace) -> None:
    """Run the backend and frontend unit and integration tests."""
    run(["uv", "run", "pytest", "--cov", "--cov-report=term:skip-covered"], BACKEND)
    run(["npm", "test"], FRONTEND)


def lint(_: argparse.Namespace) -> None:
    """Lint, format-check and type-check everything, and check the layer contracts."""
    run(["uv", "run", "ruff", "check", ".", "../scripts"], BACKEND)
    run(["uv", "run", "ruff", "format", "--check", ".", "../scripts"], BACKEND)
    run(["uv", "run", "mypy"], BACKEND)
    run(["uv", "run", "mypy", "../scripts/dev.py"], BACKEND)
    run(["uv", "run", "lint-imports"], BACKEND)
    run(["npm", "run", "lint"], FRONTEND)
    run(["npm", "run", "format:check"], FRONTEND)
    run(["npm", "run", "typecheck"], FRONTEND)
    run(["npx", "tsc", "-p", "."], E2E)
    check_client(argparse.Namespace())


def verify(args: argparse.Namespace) -> None:
    """Everything that must pass before a commit: lint, types, contracts, client, all tests."""
    lint(args)
    test(args)
    print("\nverify: all checks passed")


def fmt(_: argparse.Namespace) -> None:
    """Auto-format backend and frontend code."""
    run(["uv", "run", "ruff", "check", "--fix", ".", "../scripts"], BACKEND)
    run(["uv", "run", "ruff", "format", ".", "../scripts"], BACKEND)
    run(["npm", "run", "format"], FRONTEND)


def _generate_client(openapi_path: Path, schema_path: Path) -> None:
    run(["uv", "run", "python", "scripts/export_openapi.py", str(openapi_path)], BACKEND)
    run(["npx", "openapi-typescript", str(openapi_path), "-o", str(schema_path)], FRONTEND)
    run(["npx", "prettier", "--write", str(schema_path)], FRONTEND)


def gen_client(_: argparse.Namespace) -> None:
    """Regenerate the typed TypeScript client from the API's OpenAPI document."""
    _generate_client(OPENAPI_JSON, SCHEMA_TS)


def check_client(_: argparse.Namespace) -> None:
    """Fail if the committed client is out of date with the API (run gen-client to fix)."""
    tmp = FRONTEND / "node_modules" / ".tmp" / "client-check"
    tmp.mkdir(parents=True, exist_ok=True)
    openapi, schema = tmp / "openapi.json", FRONTEND / "src" / "api" / ".schema.check.d.ts"
    try:
        _generate_client(openapi, schema)
        stale = [
            str(path.relative_to(REPO))
            for fresh, path in ((openapi, OPENAPI_JSON), (schema, SCHEMA_TS))
            if not path.exists() or not filecmp.cmp(fresh, path, shallow=False)
        ]
    finally:
        schema.unlink(missing_ok=True)
    if stale:
        raise TaskError(f"generated client is stale ({', '.join(stale)}); run: make gen-client")
    print("generated client is up to date")


def e2e(_: argparse.Namespace) -> None:
    """Run the Playwright end-to-end tests (starts the API and web app itself)."""
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        run(["npx", "playwright", "install", "chromium"], E2E)
    run(["npx", "playwright", "test"], E2E)


def _gitleaks() -> str:
    found = shutil.which("gitleaks")
    local = REPO / "tools" / "bin" / ("gitleaks.exe" if os.name == "nt" else "gitleaks")
    if found is None and not local.exists():
        raise TaskError(
            "gitleaks not found; run scripts/cloud-setup.sh, or install it "
            "(scoop install gitleaks · brew install gitleaks · go install "
            "github.com/zricethezav/gitleaks/v8@latest)"
        )
    return found or str(local)


def secrets(_: argparse.Namespace) -> None:
    """Scan the whole git history for committed secrets with gitleaks."""
    run([_gitleaks(), "git", "--redact", "--no-banner", "."], REPO)


def secrets_staged(_: argparse.Namespace) -> None:
    """Scan only the staged changes (used by the pre-commit hook)."""
    run([_gitleaks(), "git", "--pre-commit", "--staged", "--redact", "--no-banner", "."], REPO)


def not_yet(phase: str) -> Callable[[argparse.Namespace], None]:
    def task(_: argparse.Namespace) -> None:
        raise TaskError(f"not available until {phase} (see docs/PLAN.md)")

    return task


def diagrams(_: argparse.Namespace) -> None:
    """Render every PlantUML source under docs/diagrams/ to SVG next to it."""
    sources = sorted(str(p) for p in DIAGRAMS.rglob("*.puml"))
    if not sources:
        print("no diagrams yet (docs/diagrams/**/*.puml)")
        return
    jar = Path(os.environ.get("PLANTUML_JAR", REPO / "tools" / "plantuml.jar"))
    if not jar.exists():
        raise TaskError(
            f"PlantUML not found at {jar}; run scripts/cloud-setup.sh or set PLANTUML_JAR"
        )
    run(["java", "-jar", str(jar), "-tsvg", *sources], REPO)


def report(_: argparse.Namespace) -> None:
    """Build report/build/main.pdf with tectonic."""
    tectonic = shutil.which("tectonic") or str(REPO / "tools" / "tex" / "bin" / "tectonic")
    if not Path(tectonic).exists():
        raise TaskError(
            "tectonic not found; run scripts/cloud-setup.sh or see tectonic-typesetting.github.io"
        )
    (REPORT / "build").mkdir(exist_ok=True)
    run([tectonic, "--outdir", "build", "main.tex"], REPORT)
    print(f"report: {REPORT / 'build' / 'main.pdf'}")


COMMANDS: dict[str, Callable[[argparse.Namespace], None]] = {
    "setup": setup,
    "dev": dev,
    "test": test,
    "lint": lint,
    "verify": verify,
    "format": fmt,
    "gen-client": gen_client,
    "check-client": check_client,
    "e2e": e2e,
    "secrets": secrets,
    "secrets-staged": secrets_staged,
    "seed": not_yet("P2.2"),
    "demo-reset": not_yet("P5.5"),
    "diagrams": diagrams,
    "report": report,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dev.py", description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    args = parser.parse_args(argv)
    try:
        COMMANDS[args.command](args)
    except TaskError as error:
        print(f"\nerror: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
