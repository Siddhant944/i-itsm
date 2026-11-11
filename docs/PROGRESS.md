# Progress

Updated at the end of every session. Plan: docs/PLAN.md · Decisions: docs/DECISIONS.md.

## Status: P3 Frontend MVP and first deployment — done, PR open (11 Nov)

On `claude/affectionate-mccarthy-txowq5`, cut from main after the P2 PR merged. All seven
packages are done. The phase review is in progress; its findings are recorded under P3.7 below.

`make verify` passes: 871 backend tests and 73 frontend tests. Playwright runs
Workflow 1 and Workflow 2 in a real browser against a seeded database (`make e2e`, 3 specs).

**The MVP exists.** Someone can register, report an incident, watch it get classified,
prioritised, put on an SLA and assigned; the technician can work it through every step; the
reporter can answer a question, reject a fix and rate the next one; an admin can search,
configure and audit. That is every MVP line of the brief, in three portals that look different.

**Still behind the plan, by one day less.** P3 was planned for 8-10 Nov and finished on the
11th in one session. P4 (intelligence and integrations) was planned for 11-14 Nov and has not
started, with the feature freeze on the 16th and recording on the 19th. See "Needs a human" 1.

### Done
- **Admin API (not in the plan; D-020).** The P3.4 and P3.5 screens had nothing to call, so
  this phase added 15 operations: `GET /users/directory` (names beside ids; an employee sees
  support staff only), user management (`GET/POST /users`, `PATCH /users/{id}` for role and
  active, `PUT /users/{id}/technician`), catalogue edits (`POST/PUT` categories and services,
  with a cycle check on dependencies), the SLA grid (`GET /sla/policies`, `PUT` one cell), the
  assignment settings (`GET/PUT /config/assignment`, stored in `system_config` and read per
  request so a switch takes effect on the next assignment) and the audit log (`GET /audit`
  newest first, `POST /audit/verify`). Every change is audited in the same transaction. The
  authorisation matrix now declares and proves all 60 operations.
- **P3.1 Design system and shell.** One component library over semantic colour tokens, themed
  three ways (`frontend/src/index.css`): a warm top-bar help desk for employees, a dark dense
  console for technicians, an indigo back office for admins. Badge, SLAChip (a live countdown),
  ConfidenceBadge, DataTable, FilterBar, Skeleton / Empty / Error states behind one `QueryView`
  so no screen can forget one, Toasts, NotificationBell, Modal. Sign-in and registration.
  `shell/nav.ts` is the single table of every screen; a test compares it with the route table
  in both directions, so a screen cannot exist without a link to it.
- **P3.2 Employee portal.** The report form asks the two plain-language questions of §5.1 and
  shows the AI's category with its confidence; it is applied only when the reporter clicks,
  and can be changed again. My incidents, the timeline, replying to an information request
  (with the "clock is paused" notice), and confirming or rejecting a fix with a 1-5 rating.
- **P3.3 Technician portal.** The queue most urgent first, the team queue for a Team Lead,
  workload against the 10-point cap, and one shared incident page that offers only the next
  legal step (§4) — the API still refuses anything else, and the refusal is what the user
  sees. Notes, request information, resolve, override priority (a reason is required),
  change category, and for leads the smart-assignment panel with the top three candidates and
  their reasons.
- **P3.4 Admin configuration.** Categories (keywords, required skill, priority floor),
  services (criticality, SLA tier or "follow criticality", dependencies), the SLA grid, and
  the assignment strategy with the four smart weights. An integration test adds a category
  through the API and the classifier suggests it on the very next request.
- **P3.5 Admin operations.** Dashboard with Recharts (overview cards, MTTA, MTTR, compliance,
  CSAT, reopen rate, trend, services, workload, CSV exports), the nine-filter search with
  paging and CSV, SLA violations with "run the monitor now", the audit log with its integrity
  check (a test tampers with a row in SQL and the check reports where the chain breaks), and
  users with technician profiles.
- **P3.6 First deployment — configuration only.** `render.yaml` describes the API (Docker) and
  the web app (static site), redeployed on every push to main; `docs/DEPLOY.md` has the ten
  minutes of clicking. The image now honours `PORT` and seeds a never-seeded database once
  (D-026). **Nothing is deployed yet**: that needs the Render and Neon accounts.
- **P3.7 Phase close.** Playwright WF1 (report → suggestion with confidence → priority → SLA →
  assignment → the assignee's notification and queue → the admin's audit trail, plus BR-01
  for another employee) and WF2 (acknowledge → request info with the clock paused → reply →
  resolve → reject → resolve → verify and rate → close, an illegal transition refused by the
  API, the audit chain verified) both pass. The fresh-subagent review of the phase diff
  is running; this entry is updated with what it finds.
- Smaller things that came with it: SLA countdowns run on the application's clock rather than
  the browser's (D-023), the token is per tab so three people can be signed in side by side
  (D-022), and screens poll every 10 s until WebSockets arrive in P4.8 (D-024).

### Next
- **P4**, in the plan's order: P4.1 embeddings and duplicates first (never cut), then P4.2
  correlation, P4.3 WF3 end to end, P4.4 the Gemini advisor, P4.5 predictive SLA risk.
- Carried from P2, for **P5.5** (`make demo-reset`): the seeded history was never watched by
  the monitor, so the first tick after a seed records about 170 breaches, 60 escalations and
  30 auto-closes at once. `demo-reset` should record those as it seeds, or stage a smaller
  backlog. Until then the e2e run and a fresh deployment keep the scheduler from surprising
  anyone: e2e sets `SLA_TICK_SECONDS=0`; on a deployment the first tick is simply large.
- For **P5.6** (UX pass): the sidebar portals are not yet comfortable below about 900 px wide,
  and the frontend bundle is one chunk (Recharts is most of it) that could be split by portal.

### Needs a human
1. **Decide the P4 cuts now, together.** Five working days remain before the freeze for a
   phase planned at four, with nothing in reserve. The plan's cut order is Telegram /report
   chatbot → voice input → Locust → health map → Google Sign-In → Telegram alerts. Cutting the
   first two today costs little and protects the never-cut list (duplicates, correlation, WF3,
   Gemini with fallback, predictive SLA).
2. **Review this phase and merge the PR.** Add the `e2e` label so Playwright runs in CI: this
   phase is all UI.
3. **Create the Render and Neon accounts and deploy**, following docs/DEPLOY.md (about ten
   minutes, no card). Then do Workflow 1 by hand on the deployed URL — that is P3.6's
   acceptance test and the one thing in this phase nobody has been able to check.
4. **Dry run 1** was planned for 10 Nov: `make seed && make dev`, then walk Workflows 1 and 2
   with the demo accounts in the README, three tabs side by side.
5. Before P4.4: a Gemini API key and the model names from Google AI Studio.
6. Confirm the video file-name year with the IC.

## Previous: P2 Persistence, services, API (merged 11 Nov, PR #3)

All eleven P2 packages done; 789 backend tests at 97 % coverage, also green on PostgreSQL 16.
The package-by-package record and the hosting proposal are kept below because P3.6 and the
report's deployment section still lean on them.

### Done in P2
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
- **P2.4 Audit and the IncidentService facade.** `app/domain/audit.py` implements
  h_i = SHA256(h_(i-1) || record_i) over a canonical JSON rendering; `app/services/audit.py`
  appends through the caller's Unit of Work (never commits) and reads the head under a row lock.
  Five integration tests edit, delete and replay rows in `audit_log` with raw SQL and the
  admin's verify finds every tampering, across page boundaries; the unique hash blocks a replay
  outright. Revision 0002 adds `users.last_login_at`.
  `app/services/incident_service.py` is the facade the routers call: one method per thing a
  caller can do, each loading the aggregate, checking who is asking, letting the aggregate
  decide whether the move is legal, saving, auditing in the same transaction, committing, then
  notifying. `app/domain/access.py` holds BR-01, BR-02 and BR-03 as functions over the role's
  permissions and the incident's own reporter, assignee and team — no isinstance anywhere.
  Reporting runs the whole §4 opening (suggest, prioritise, set the SLA, classify, rank under
  the 10-point cap, assign); nobody with capacity queues it for the Team Lead, and nothing
  classifiable leaves it NEW for triage, because §4 runs NEW → CLASSIFIED → ASSIGNED.
  `PostCommitDispatcher` delivers events only after the commit, so a failing subscriber is
  logged and a failed commit leaves neither the change nor its audit record.
- **P2.5 Notifications.** The §5.4 table is data in `app/domain/notifications.py` — ten events,
  their audiences and channels, including the two conditions the blueprint writes in prose (the
  Team Lead only at P1/P2, Telegram only at P1/P2); a parametrised test walks every row.
  Channels are a factory over one port (in-app, email, a Telegram placeholder until P4.9), the
  SMTP adapter falls back to the console when `SMTP_HOST` is empty, and every notification is
  stored before it is sent so the bell reads it and the three retries are visible. Found and
  fixed two real bugs: `configure_logging` replaced the root handler list, and Alembic's
  `fileConfig` disabled every existing logger.
- **P2.6 API routers.** 30 routes then: report, the while-typing suggestion, my incidents, my
  queue, one incident in full, assignment advice, the twelve lifecycle actions, the bell and the
  catalogue reads. The role check is a route dependency so it appears in the OpenAPI document;
  responses carry the live SLA status with both deadlines. Fixed an ordering bug: reporting
  audited the incident before inserting its row, so the audit foreign key failed whenever the
  opening steps had something to say.
- **P2.7 Search, CSV export and the dashboards.** The nine §9 filters plus free text are one
  immutable `IncidentQuery`, narrowed by the service to what the caller may see before it runs.
  The dashboards are one call: the overview cards, MTTA, MTTR, SLA compliance, CSAT, the reopen
  rate, the workload table against the 10-point cap, the service analysis and the trend; the
  repository counts and `app/domain/analytics.py` divides, so "nothing resolved yet" reads as no
  average rather than zero. Incidents store four moments derived from their SLA clock so the
  status filter is an indexable comparison (D-018, revision 0003). A 38-case contract suite runs
  every filter and figure against both repository implementations and caught three real
  disagreements between them.
- **P2.8 SLA monitor.** One `tick()` warns at 75 %, records a breach once per cycle, asks the
  escalation chain and auto-closes after 72 hours — all idempotent, because it runs every 30 s.
  BR-08 end to end: an unacknowledged P1 escalates just after 5, 10 and 15 minutes to the team's
  lead, an administrator, then the IT manager, and stops. BR-03 closes an unanswered resolution
  strictly after 72 hours with no actor on the record. The scheduler converts 30 clock seconds
  into real seconds through the clock itself (D-003), so the demo's ×10 clock runs it every 3 s.
  `/dev/clock` moves time in test and demo only, and prod refuses `CLOCK_MODE=fake` (D-009).
- **P2.9 Authorisation matrix.** `tests/integration/test_authz_matrix.py` declares, for all 45
  operations, which of the six roles may call each, and proves it — 92 cases, plus a check that
  everything but `/health`, `/auth/register` and `/auth/login` answers 401 without a token, and
  a comparison with the OpenAPI document in both directions so a new endpoint cannot be added
  without saying who may call it.

- **P2.10 Hosting proposal.** Checked against the providers' own pages on 4 Nov 2026 (free
  tiers have shrunk a lot this year; Railway, Fly.io and Koyeb no longer have a usable one —
  Koyeb now wants a $29 card hold).

  **Recommended: Render for the API and the web app, Neon for PostgreSQL.** Neither needs a
  credit card.

  | | Render free | Neon free |
  |---|---|---|
  | What we would run on it | the FastAPI service and the static frontend | the database |
  | Size | 0.1 CPU, 512 MB RAM | 1 GB storage per project, autoscales to 2 CU |
  | Allowance | 750 instance hours per workspace per month | 100 CU-hours and 5 GB transfer per project per month |
  | Idle behaviour | spins down after 15 min; ~1 min cold start | compute scales to zero after 5 min, back in a few hundred ms |
  | Expiry | none | none — "the Free plan is permanent (not a trial)" |

  Why not Render's own free PostgreSQL: it is 1 GB and one per workspace, but it **expires 30
  days after creation**, with a 14-day grace period after which Render deletes the database and
  its data. Created in early November it would survive the 21 Nov submission and then vanish,
  so anyone opening our link in December would find an empty app. Neon's free plan has no
  expiry, which is worth the second account.

  **Two consequences for our code, both already handled:**
  1. *A spun-down service runs no scheduler.* Our SLA monitor ticks every 30 s of clock time
     (D-003), and a Render free service that has had no traffic for 15 minutes is not running at
     all, so escalations and the 72-hour auto-close would only catch up when someone next opens
     the app. For the demo we keep the service warm (open it a few minutes before recording, or
     ping `/health` on a schedule); `POST /sla/tick` also runs the monitor on demand. Worth one
     sentence in the report's deployment section rather than a surprise on camera.
  2. *Render free blocks outbound ports 25, 465 and 587*, which is exactly what SMTP email
     needs. Our email adapter already falls back to the console when `SMTP_HOST` is empty
     (§5.4, §7), so the deployment simply runs without email and everything else works; in-app
     notifications are unaffected. If we want real email later it has to be an HTTP API rather
     than SMTP.

  Also note Render's free filesystem is ephemeral and has no persistent disk, so the deployed
  app must use PostgreSQL, never the SQLite file — which is what `DATABASE_URL` already decides.

  **Fallback, if we would rather keep one account:** Render for all three (web service, static
  site, Postgres), accepting the 30-day database expiry. Simpler to set up, fine for the
  submission window, not fine afterwards.

  **What a human needs to do before P3.6:** create a Render account and a Neon account (no card
  for either), make one Neon project in the region nearest Render's, and put its connection
  string in Render as `DATABASE_URL` plus a strong `JWT_SECRET`. The API image already runs
  `alembic upgrade head` before serving, so the schema builds itself on first deploy.

- **P2.11 Phase close.** A fresh-context subagent reviewed the whole phase diff against
  AGENTS.md, the blueprint and DECISIONS.md. It found three bugs that would have shipped and
  several smaller ones; all are fixed, each with a test that fails without the fix. The three
  that mattered: the stored SLA deadline used the live target instead of the one frozen at
  RESOLVED, so a re-prioritised incident read ON_TRACK in the search and BREACHED on its own
  page (D-017, D-018); the §5.4 "Escalated" and auto-close "Closed" notifications never went
  out, and the test that claimed otherwise built its own wiring; and work notes could still be
  added to CLOSED and CANCELLED incidents. Fixing the second exposed another: escalation
  stalled when the assignee was already the team's lead. Also fixed: the audit head lock did
  not serialise on PostgreSQL, a truncated audit tail was undetectable, §8's 503 row was
  unreachable, the login response revealed which accounts exist (D-019), the monitor retried an
  impossible escalation every 30 s for ever, reassignment double-counted a workload, the trend
  chart bucketed by UTC rather than IST, two dashboard panels disagreed about "breached", D-004's
  documented fallback was not implemented, a duplicate could be linked to an unseen incident,
  and a CSV cell could be a live formula.


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
