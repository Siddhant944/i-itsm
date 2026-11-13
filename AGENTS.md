# I-ITSM: instructions for AI coding agents

Intelligent IT Service Management & Incident Resolution System for the campus IT helpdesk.
CS F213 group project; submission 21 Nov 2026 (hard deadline 22 Nov).

- Requirements: docs/source/OOP_S1_2026-2027_Project.pdf (wins every conflict)
- Design: docs/blueprint.md (source of truth; § numbers below refer to it)
- Plan, status, decisions: docs/PLAN.md, docs/PROGRESS.md, docs/DECISIONS.md
- Ask before deviating from the blueprint; log every agreed deviation in DECISIONS.md.

## Commands
- make setup · make dev · make test · make e2e · make seed · make demo-reset · make diagrams · make test-report · make report
- make verify = lint + type-check + all tests. It must pass before every commit.

## Stack
- Backend: Python 3.12 (uv), FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, APScheduler, Google Gen AI SDK, pytest, Ruff, mypy --strict
- Frontend: React, TypeScript (strict), Vite, Tailwind, typed client generated from OpenAPI, Recharts, React Flow, Vitest, Playwright
- Data: SQLite for local dev (foreign_keys=ON, WAL); PostgreSQL in Docker and deployment; CI tests both

## Architecture (§2): dependencies point inward
| Layer | Package | May import |
|---|---|---|
| API | backend/app/api | services, domain, core |
| Services | backend/app/services | domain, core |
| Domain | backend/app/domain | core only; never FastAPI, SQLAlchemy or HTTP clients |
| Persistence | backend/app/repositories | domain, core |
| Core | backend/app/core | config, security, Clock, logging |

- Repository and adapter interfaces live in the domain; implementations live outside it.
- External services (Gemini, SMTP, Telegram, Google OAuth) are reached only through adapters, each with a deterministic fallback or fake.
- Routers stay thin: validate input, call the IncidentService facade, map the result.
- Audit records are written in the same transaction as the change; notifications and WebSocket pushes go out after commit.

## OOP rules
- Inheritance only for true is-a. Users: User (abstract) → Employee, Technician, Administrator; TeamLead extends Technician; ITManager extends Administrator. Permissions come from a role → permission map, never isinstance checks.
- Encapsulation: name-mangled attributes (__x) behind read-only @property; state changes only through intention-revealing methods such as incident.acknowledge(actor, clock); value objects are frozen dataclasses; collections are exposed as tuples or frozensets.
- Interfaces are ABCs. Every pattern class (§10) has a docstring naming its pattern and the problem it solves.
- Errors: only the ITSMError hierarchy (§8); global handlers map it to HTTP codes; never leak stack traces.
- Time: never call datetime.now(); inject Clock (System, Fake, Accelerated). Store timezone-aware UTC; display IST.
- Tunable numbers from §5–§6 (weights, thresholds, capacities, timings) are defined once with their § reference, admin-editable where §3 says so.

## Incident lifecycle (§4): exactly these 20 transitions; anything else raises InvalidStateTransitionError
- NEW → CLASSIFIED, CANCELLED
- CLASSIFIED → ASSIGNED, CANCELLED
- ASSIGNED → ACKNOWLEDGED, ASSIGNED (reassign or escalate), CANCELLED
- ACKNOWLEDGED → IN_PROGRESS, ASSIGNED, CANCELLED
- IN_PROGRESS → ON_HOLD, RESOLVED, ASSIGNED, CANCELLED
- ON_HOLD → IN_PROGRESS, CANCELLED
- RESOLVED → VERIFIED, IN_PROGRESS (fix rejected), CLOSED (auto-close after 72 h)
- VERIFIED → CLOSED
- CLOSED and CANCELLED are terminal

## Tests
- Domain rules are written test-first. Each business rule BR-01 to BR-10 (§7) has a test whose name contains its ID.
- Tests are deterministic: FakeClock, fake adapters, no network. Live-API tests are marked `live` and skipped in CI.
- A bug found after merge gets a GitHub issue, a regression test, and a fix commit that references the issue.

## Security
- Never open, print or commit .env or any secret. Settings come from app/core/config.py; .env.example lists every variable.
- Every incident route checks role and ownership (BR-01) in a FastAPI dependency.
- All input is validated by Pydantic; no SQL is built from strings.

## Frontend
- Employee, Technician and Admin portals look visibly different, and each has navigation linking every screen of that role.
- AI suggestions show their confidence and can be overridden; nothing is applied silently.
- Every API call goes through the generated client and handles loading, empty and error states.

## Sessions, git and usage
- We build in Claude Code cloud sessions on one Pro account, one session at a time; all four of us review at each phase end.
- Each phase runs in a fresh cloud session on the `claude/*` branch that session is given, cut from main after the previous phase PR is merged (D-001). Never push to another branch.
- When told "continue": make sure the session branch is based on the latest main, read docs/PLAN.md and docs/PROGRESS.md, and carry on with the next unfinished package.
- One session branch per phase; small Conventional Commits (feat:, fix:, test:, docs:, refactor:, chore:); push before a session ends; never push to main.
- End of phase: a fresh subagent reviews the phase diff; fix its findings; update docs/PROGRESS.md (done, next, needs a human); open the PR; stop with a short summary and five bullets per module for its owner to present. We merge.
- Save usage: read only the files a task needs, keep command output short, run the narrowest relevant tests while iterating, `make verify` before each commit, Playwright only at phase ends.
