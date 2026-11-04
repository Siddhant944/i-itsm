# Progress

Updated at the end of every session. Plan: docs/PLAN.md · Decisions: docs/DECISIONS.md.

## Status: P1 Domain core, in review (3 Nov)

All P1 packages are done on `claude/funny-fermi-bjxlhr` and in the P1 PR. Domain coverage 97 %;
286 backend tests. Merge the PR, then start P2 in a fresh session with "continue".

### Done
- P1.1 Clock and errors (tests first): `app/core/clock.py` (Clock ABC; SystemClock, the only
  wall-clock read; FakeClock that never moves backwards; AcceleratedClock with an injectable
  monotonic source and `real_seconds()` for D-003) and `app/domain/errors.py` (ITSMError, 8 groups,
  14 specific errors with stable codes and read-only details). 18 new unit tests.
- P1.2 Users and permissions (tests first): `app/domain/value_objects.py` (EmailAddress,
  SkillSet over a frozenset with `coverage()`), `app/domain/permissions.py` (Role, Portal,
  Permission; the role → permission map built up the is-a hierarchy; escalation levels 0-3) and
  `app/domain/users.py` (abstract User → Employee, Technician → TeamLead, Administrator →
  ITManager; name-mangled read-only state; UserFactory). 43 new unit tests.
- P1.3 Incident aggregate and State (tests first): `app/domain/states.py` (10 states, 20 legal
  transitions, registry), `app/domain/events.py` (domain events, EventBus) and
  `app/domain/incident.py` (Incident composing work notes, resolution and feedback;
  IncidentFactory with INC-YYYY-NNNN IDs). The 100-pair matrix, BR-03 and BR-04 tests pass;
  domain coverage 98 %. Deferred: the SLA clock inside the incident (joins in P1.5) and
  `scripts/gen_state_diagram.py` (P6.1, generated from the state registry).
- P1.4 Priority (tests first): `app/domain/priority.py` (Priority P1-P4; PriorityStrategy with
  the floor applied once in `assess`; WeightedProduct S = I × U × C with the §5.1 thresholds;
  an editable impact × urgency Matrix) and `Incident.prioritise` / `override_priority` (reason
  required, PriorityChanged event). All 27 combinations give 4/6/10/7; 48 new tests.
- P1.5 SLA (tests first): `app/domain/sla.py` (tiers, the §5.2 table with Silver ×2 and Bronze
  ×4, SLAPolicyBook with MissingSLAConfigurationError and the Gold fallback (D-016), SLAClock with
  respond, pause, resume, stop and restart, ThresholdRiskEstimator at 75 %). The Incident now owns
  its SLA clock: acknowledge meets the response SLA, hold pauses, resume and the reporter's answer
  resume, resolve and cancel stop, reopen restarts without counting resolved time. 13 new tests.
- P1.6 Assignment (tests first): `app/domain/assignment.py` (Template Method `select()` filters
  available, active technicians under the 10-point cap; Skill, Load and Smart strategies with
  reasons such as "2/2 skills · 60 % capacity free · senior · 5 past fixes on this service";
  `check_capacity` for manual assignment; registry). 8 new tests including BR-06.
- P1.7 Escalation: `app/domain/escalation.py` (Chain of Responsibility Technician → Team Lead →
  Administrator → IT Manager; unacknowledged P1/P2 move up one level per missed response
  target, strictly after each multiple; a resolution breach goes to the Team Lead; no repeat
  escalation to the current level). 10 new tests including BR-08.

- P1.9 Phase close: subagent review found 5 issues, all fixed with regression tests
  (refused actions now leave the incident unchanged; the SLA clock starts only before assignment;
  response time stops counting after cancellation; met SLA results are frozen against later
  retargets (D-017); IncidentState is an ABC). Deferred to P6.1: `scripts/gen_state_diagram.py`.

### Next
- P2 Persistence, services, API: P2.1 ORM and migrations first (the SQLAlchemy repositories join
  `tests/contract/test_repository_contract.py`).

### Needs a human
1. Merge the P1 PR once CI is green (add the `e2e` label only at phase ends that touch the UI).
2. Before P2.10 / P3: create the hosting accounts we will propose. Before P4: a Gemini API key.
3. Confirm the video file-name year with the IC.

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
