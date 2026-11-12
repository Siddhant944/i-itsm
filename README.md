# I-ITSM

[![CI](https://github.com/Siddhant944/i-itsm/actions/workflows/ci.yml/badge.svg)](https://github.com/Siddhant944/i-itsm/actions/workflows/ci.yml)

**Intelligent IT Service Management & Incident Resolution System** for a campus IT helpdesk.
Employees report problems; the system classifies, prioritises, assigns, tracks SLAs, escalates,
notifies and audits every step until the incident is verified and closed.

CS F213 / MAC F212 Object-Oriented Programming, Semester I 2026–27 · Group 15

> Status: **P3, the MVP**. The Employee, Technician and Admin portals work end to end on the full backend; the intelligence features land in P4 (see [docs/PLAN.md](docs/PLAN.md)). Deploying: [docs/DEPLOY.md](docs/DEPLOY.md).

## Quick start (Linux / macOS)

Needs [uv](https://docs.astral.sh/uv/), Node.js 22+ and git. uv installs Python 3.12 itself.

```bash
make setup
```

```bash
make dev
```

Then open http://localhost:5173 (the API runs at http://127.0.0.1:8000, docs at `/docs`).
Run `make seed` first for the demo accounts below and three months of history to look at.

## Windows, without make or Docker

Install uv, Node.js and git:

```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
winget install OpenJS.NodeJS.LTS Git.Git
```

Then, in the repository folder (PowerShell or cmd), use the same runner that `make` uses:

```bash
uv run scripts/dev.py setup
```

```bash
uv run scripts/dev.py dev
```

The database is a local SQLite file (`backend/itsm.db`); nothing else is needed. Create its tables
with `make migrate` (Alembic), which is also what the Docker image runs before it serves. Every
`make <target>` below works as `uv run scripts/dev.py <target>`. The git hook also needs gitleaks
(`scoop install gitleaks`).

## Docker (API + web + PostgreSQL)

```bash
docker compose up --build
```

Then open http://localhost:8080.

## Commands

| Command | What it does |
|---|---|
| `make setup` | Install backend, frontend and e2e dependencies and the git hooks |
| `make dev` | Run the API and the web app with reload |
| `make test` | Backend (pytest) and frontend (Vitest) tests |
| `make verify` | Lint, format, types, layer contracts, generated-client check and all tests; must pass before every commit |
| `make e2e` | Playwright end-to-end tests |
| `make gen-client` | Regenerate the typed TypeScript client from the API's OpenAPI document |
| `make migrate` | Bring the database at `DATABASE_URL` up to the latest Alembic migration |
| `make seed` | Migrate, then load the campus catalogue, the demo accounts and 420 historical incidents |
| `make demo-reset` | Reset the demo: reseed on an accelerated clock (from P5) |
| `make diagrams` / `make report` | Render PlantUML diagrams / build the report PDF with tectonic |

Configuration lives in environment variables; copy `.env.example` to `.env` (never commit it).
Without API keys the app uses its fallbacks: rule-based AI, console email, no Telegram.

## Demo accounts

Added with the seed data in P2 (one account per role: Employee, Technician, Team Lead, Administrator, IT Manager).

## Architecture

A layered modular monolith; every dependency points inward to a framework-free domain
(blueprint §2, enforced by import-linter):

| Layer | Package | May import |
|---|---|---|
| API | `backend/app/api` | services, domain, core |
| Services | `backend/app/services` | domain, core |
| Domain | `backend/app/domain` | core only |
| Persistence / adapters | `backend/app/repositories`, `backend/app/adapters` | domain, core |
| Core | `backend/app/core` | — |

Frontend: React + TypeScript + Tailwind (`frontend/`), talking to the API only through the client generated from OpenAPI.
Data: SQLite locally, PostgreSQL in Docker and deployment.

## Demo accounts

`make seed` creates one account per role, all with the password `demo1234`:

| Email | Role | Portal |
| --- | --- | --- |
| `employee@campus.edu` | Employee | Employee |
| `technician@campus.edu` | Technician | Technician |
| `lead@campus.edu` | Team Lead | Technician |
| `admin@campus.edu` | Administrator | Admin |
| `manager@campus.edu` | IT Manager | Admin |

These are demo credentials for a seeded database. Each browser tab holds its own sign-in, so the
three portals can be open side by side as three different people.

## Tests

```bash
make test
```

The backend suite runs on SQLite by default; set `TEST_DATABASE_URL` to a PostgreSQL URL to run it there (CI runs both).
The repository contract suite (`backend/tests/contract`) runs every test against the in-memory and the
SQLAlchemy repositories, and `backend/tests/integration/test_migrations.py` fails if the models and the
migrations drift apart.

## Documentation

- [Requirements](docs/source/OOP_S1_2026-2027_Project.pdf) · [Blueprint](docs/blueprint.md) · [Plan](docs/PLAN.md) · [Progress](docs/PROGRESS.md) · [Decisions](docs/DECISIONS.md)
- Report sources: `report/` (`make report`)

## Team

| Member | Module |
|---|---|
| Tushar B (M1) | Domain and lifecycle |
| Siddhant L Pathak (M2) | Intelligence and SLA |
| Shri Krishna P (M3) | Platform |
| Ishaan S (M4) | Frontend and QA |
