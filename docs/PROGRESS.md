# Progress

Updated at the end of every session. Plan: docs/PLAN.md · Decisions: docs/DECISIONS.md.

## Status: P2 Persistence, services, API — in progress (4 Nov)

On `claude/jolly-newton-82k47h`, cut from main after the P1 PR merged. P2.1, P2.2 and P2.3 are
done and pushed, together with the audit half of P2.4. `make verify` passes (442 backend tests,
98 % coverage) and the whole suite also passes against PostgreSQL 16, migrations and a full seed
included.

### Done
- **P2.1 ORM and migrations.** `app/domain/catalogue.py` adds the entities the schema needed:
  Skill, Category (keywords, optional priority floor), ITService (criticality, SLA tier,
  dependencies) and Team, plus `required_skills_for` for D-002. `SLAClock.restore`,
  `Incident.restore` and `Team.restore` let the mappers rebuild aggregates through named
  constructors instead of writing to name-mangled state; the SLA clock now banks paused time as
  one accumulated timedelta (the pause list was only ever summed), which is what the schema
  stores. `Incident` gained the escalation level §9 keeps on the row, with `escalate()`.
  `app/repositories/sqlalchemy/` holds the 18 tables with the §9 indexes, enums stored as the
  domain's own strings with CHECK constraints, a `UtcDateTime` column that refuses naive values,
  mappers, and repositories for incidents, users and the catalogue behind a Unit of Work that
  shares one session. Optimistic locking records the version each incident was read at, so a new
  work note contends with a status change. Alembic revision 0001 creates everything and
  `tests/integration/test_migrations.py` fails if the models and the migrations drift;
  `make migrate` is new, and the API image migrates before it serves.
- **P2.2 Seed data.** `app/seed/` (campus data, people, history generator, runner). Ten skills,
  ten categories, fourteen services with twenty dependency edges, five teams, twelve SLA
  policies, 51 accounts (one per role, password `demo1234`) and 420 historical incidents driven
  through the real aggregate methods on a FakeClock. 246 closed, open work in every state, 75 %
  response compliance, reopens, escalations and linked duplicates (D-005). Deterministic for a
  given clock, idempotent through a marker row, and numbers come from the repository's own
  per-year counter so the next reported incident continues the series.
- **P2.3 Auth and security.** `app/domain/credentials.py` holds the §8 lockout rule (five
  failures, fifteen minutes, an expired lock restarts the count). `app/core/security.py` has
  Argon2id hashing and HS256 tokens whose expiry is checked against the injected Clock, with a
  fast fake hasher for tests. `AuthService` registers Employees only (D-008), answers an unknown
  email exactly like a wrong password, and audits every outcome. `app/api/` gained the §8 error
  table in one place, request dependencies (`Depends(requires(permission))` so a route cannot
  forget its check) and POST /auth/register, POST /auth/login, GET /auth/me. The typed TS client
  is regenerated.
- **P2.4 part 1: audit.** `app/domain/audit.py` implements h_i = SHA256(h_(i-1) || record_i) over
  a canonical JSON rendering; `app/services/audit.py` appends through the caller's Unit of Work
  (never commits) and reads the head under a row lock. Five integration tests edit, delete and
  replay rows in `audit_log` with raw SQL and the admin's verify finds every tampering, across
  page boundaries; the unique hash blocks a replay outright. Revision 0002 adds
  `users.last_login_at`.

### Next
- P2.4 part 2: the IncidentService facade (BR-01, BR-02, BR-03, BR-10), publishing incident
  events into the audit chain in-transaction and notifications after commit.
- Then P2.5 notifications, P2.6 routers and errors for incidents, P2.7 search and analytics,
  P2.8 SLA monitor, P2.9 authorisation matrix and client, P2.10 hosting research, P2.11 close.

### Needs a human
1. Nothing blocking yet this phase. At P2.10 we will propose hosting; create those accounts
   before P3.6.
2. Before P4: a Gemini API key and model names.
3. Confirm the video file-name year with the IC.

## Previous: P1 Domain core (merged 4 Nov, PR #2)

All nine P1 packages done: Clock and errors, users and permissions, the Incident aggregate with
the State pattern and its 20 transitions, priority, SLA, assignment, escalation, ports and the
in-memory repositories, and the phase review. Domain coverage 97 %; 286 backend tests.

## Previous: P0 Foundations (merged 3 Nov, PR #1)

### Done
- P0.1 Sources moved to `docs/source/` and `docs/blueprint.md`; PLAN, PROGRESS and DECISIONS created; AGENTS.md session rules updated (D-001).
- P0.2 Backend skeleton: FastAPI app factory, `/health` with a database probe, typed settings, SQLite pragmas, Ruff, mypy --strict, pytest-cov and six import-linter layer contracts.
- P0.3 Frontend skeleton: Vite, React 19, strict TS, Tailwind 4, TanStack Query, generated OpenAPI client, placeholder health page with loading, error and success states; Playwright smoke test.
- P0.4 Tooling: `scripts/dev.py` (cross-platform) behind the Makefile, local pre-commit hooks with gitleaks, Docker Compose (api, web, postgres), `.env.example`, `.claude/settings.json`, `scripts/cloud-setup.sh`, LaTeX report skeleton built with tectonic.
- P0.6 Fresh clone `make setup && make verify` passes; `make dev`, `make e2e`, `make report` and `docker compose up` (api healthy on PostgreSQL, web on :8080) checked by hand; subagent review: 8 findings, all fixed (empty-secret handling, Windows line endings and process cleanup, cloud-setup repo detection, exact version pins, a Ruff ban on wall-clock calls).
- P0.5 CI: `ci.yml` (gitleaks; backend on SQLite and PostgreSQL; frontend and client freshness), `e2e.yml` and `report.yml` (only on PRs labelled `e2e` or `report`); issue and PR templates.

- Early report drafts (P6.2): chapters 1 Problem analysis, 2 Requirements (FR-01 to FR-31, NFR-01 to NFR-10, roles, BR-01 to BR-10) and 5 Technology stack with the nine answers. Draft 1, for the owners (M1, M2) to review; Chapter 5 versions are regenerated from the lock files at freeze.

### Next
- P1 Domain core (new session, branch from main after the P0 PR merges): P1.1 Clock and errors first.

### Needs a human
1. Create repository labels `e2e` and `report` (Issues → Labels → New label). Add `e2e` to each phase-end PR so Playwright runs in CI, and `report` to PRs that change the report or diagrams. Merge the P0 PR once CI is green.
2. Paste `scripts/cloud-setup.sh` into the cloud environment's setup script. The network policy must allow PyPI, npm, proxy.golang.org, repo1.maven.org and conda.anaconda.org (later also generativelanguage.googleapis.com and api.telegram.org).
3. Confirm the video file-name year (`15_OOP_S1_2025-2026_Project` vs 2026-2027) with the IC.
4. Before P4: Gemini API key and model names (Google AI Studio). Before P4/P5: SMTP app password, Telegram bot token, Google OAuth client ID and campus domain. These go into deployment secrets, never the repo.
5. After P2.10: create the hosting accounts we propose. Optional: branch protection on main (needs GitHub Pro for a private repo).
6. P4.1: review the ~50 labelled duplicate pairs.
