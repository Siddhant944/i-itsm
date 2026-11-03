# I-ITSM build plan (approved 3 Nov 2026, revision 2)

## Context
The repo holds only the sources: the requirements PDF (it wins every conflict), Blueprint v2 (the source of truth), the superseded v1 brief, AGENTS.md and a stub README. This plan turns the six phases into work packages of a few hours each. Every package names an owner, its dependencies, files, acceptance tests and the rubric line it earns. The goal is the full 120 marks, protected in this order: MVP → core-rule tests → §6 features → extras.

**Team, group 15** (owners per blueprint §15): M1 Domain and lifecycle = Tushar B · M2 Intelligence and SLA = Siddhant L Pathak · M3 Platform = Shri Krishna P · M4 Frontend and QA = Ishaan S. The video file is `15_OOP_S1_2025-2026_Project` unless the IC corrects the year.

Rubric keys: **FN** Functionality 60 · **TD** Technical depth 15 · **DA** Design and architecture 10 · **UX** User experience 10 · **IN** Innovation 10 · **DOC** Documentation and presentation 10 · **TST** Testing 5.

## Decisions (logged in DECISIONS.md at P0)
- **D-001 Branches:** P0 goes on `claude/funny-fermi-bjxlhr`. Each later phase runs in a fresh cloud session on its own `claude/*` branch, cut from main after you merge the previous PR.
- **D-002 Required skills:** S_r = the category's required skill ∪ the service's optional `required_skill_id`. That is one extra column on `services`; the table count stays at 18.
- **D-003 Monitor tick:** the SLA monitor ticks every 30 s of *clock* time. Under ×10 it runs every 3 real seconds, so P1 escalation at 5, 10 and 15 min happens at 30, 60 and 90 real seconds.
- **D-004 Team Lead:** the lead of the assignee's team. For an unassigned incident, the lead of the team that best covers S_r, falling back to the Service Desk team.
- **D-005 Duplicate subscription:** done through the cancelled child's `parent_id`, so no extra table is needed.
- **D-006 Info replies:** the reporter's reply to an info request resumes ON_HOLD → IN_PROGRESS, audited with the reporter as actor.
- **D-007 Added tools:** import-linter (enforces the §2 layers in `make verify`); TanStack Query; openapi-typescript + openapi-fetch; a pure-Python TF-IDF; **tectonic** for the report both locally and in CI; plantuml.jar for diagrams.
- **D-008 Self-registration:** open to any email unless `ALLOWED_EMAIL_DOMAINS` is set. Google Sign-In always checks `hd`.
- **D-009 Clock control:** a `/dev/clock` endpoint exists only when `APP_ENV` ∈ {test, demo}, for Playwright and the demo.
- **D-010 CI budget:** the repo is private, with 2,000 Actions minutes a month. CI runs only on PRs, pushes to main and manual runs. It cancels superseded runs and caches uv and npm. The report job runs only on PRs that touch its paths, and Playwright only on PRs labelled `e2e`. Between PRs, `make verify` in the session is the gate.
- **D-011 Secrets:** gitleaks runs in pre-commit and CI instead of GitHub secret scanning. Branch protection is optional, because it needs GitHub Pro on a private repo.
- **D-012 Trimmed P0:** no CODEOWNERS file (a deviation from §2; ownership lives in PLAN.md). The four lost blueprint diagrams aren't restored, because AGENTS.md covers them and P6 generates the real ones from code. A single cross-platform `scripts/dev.py` replaces per-OS scripts.

## P0 Foundations — Wed 4 Nov (this session)
| ID | Package | Owner | Deps | Files | Acceptance | Rubric |
|---|---|---|---|---|---|---|
| P0.1 | Repo layout and docs | M3 | – | `git mv` the PDFs to `docs/source/` and the blueprint to `docs/blueprint.md`; `docs/{PLAN,PROGRESS,DECISIONS}.md`; `.gitignore`, `.editorconfig`; README skeleton with CI badge | Files present; AGENTS.md paths resolve | DOC |
| P0.2 | Backend skeleton | M3 | P0.1 | `backend/pyproject.toml` (uv, `requires-python ==3.12.*`, `.python-version`); `app/main.py` app factory; `app/api/health.py`; `app/core/{config,logging}.py`; empty layer packages; Ruff, `mypy --strict`, pytest-cov and import-linter config | `tests/integration/test_health.py` green; `lint-imports` and mypy clean | TD, DA |
| P0.3 | Frontend skeleton | M4 | P0.2 | `frontend/` (Vite, React, TS strict, Tailwind, ESLint, Prettier, Vitest, React Router, TanStack Query); `scripts/export_openapi.py` → `frontend/src/api/schema.d.ts`; placeholder page showing /health with loading and error states; `e2e/` Playwright config and smoke test | Vitest covers the three states; Playwright smoke passes locally | UX, TD |
| P0.4 | Tooling | M3 | P0.2–3 | `scripts/dev.py` (cross-platform: setup, dev, test, seed, demo-reset, gen-client; run with `uv run`); a Makefile that delegates to it; `.pre-commit-config.yaml` (Ruff, mypy, ESLint, Prettier, **gitleaks**); `docker-compose.yml` (api, web, postgres) and Dockerfiles; `.env.example`; `.claude/settings.json` (allow make, uv, npm, npx, docker, git and gh; deny reads of `.env`, `.env.local` and `.env.production`); `scripts/cloud-setup.sh` (also installs tectonic, plantuml.jar and gitleaks); `report/` LaTeX skeleton in deliverables order; Windows commands in the README | `make dev` and `uv run python scripts/dev.py dev` both serve /health and the UI; `docker compose up` is healthy; `make report` builds the skeleton with tectonic; gitleaks is clean | TD, DOC |
| P0.5 | CI and templates | M3 | P0.4 | `.github/workflows/ci.yml` (triggers: pull_request, push to main, workflow_dispatch; concurrency with cancel-in-progress; uv and npm caches). Jobs: gitleaks; backend lint, types, import contracts and tests on a {sqlite, postgres} matrix with coverage summary; frontend lint, types, test and build; generated-client freshness. `e2e.yml` (only on PRs labelled `e2e`, or run by hand) and `report.yml` (paths `report/**`, `docs/diagrams/**`, tectonic). Issue templates (bug, feature) and a PR template | CI green on the P0 PR | TST, TD |
| P0.6 | Phase close | all | P0.1–5 | PROGRESS.md | Fresh clone: `make setup && make verify` passes; subagent review findings fixed; PR opened; CI green on it | – |

## P1 Domain core — Thu 5 Nov (test-first; framework-free)
| ID | Package | Owner | Deps | Files (`backend/app/…`) | Acceptance (in `tests/unit/domain/`) | Rubric |
|---|---|---|---|---|---|---|
| P1.1 | Clock and errors | M1 | P0 | `core/clock.py` (Clock ABC; System, Fake and Accelerated clocks); `domain/errors.py` (ITSMError, 8 groups, 14 specifics with stable codes) | FakeClock advance; ×10 scaling; hierarchy is exactly 8 groups and 14 specifics | DA, TST |
| P1.2 | Users and permissions | M1 | P1.1 | `domain/users.py` (User ABC → Employee, Technician → TeamLead, Administrator → ITManager); `domain/permissions.py` (role → frozenset); `UserFactory`; EmailAddress and SkillSet value objects | Permission table per role; escalation levels 0–3; attributes are read-only | FN, DA |
| P1.3 | Incident aggregate and State | M1 | P1.2 | `domain/incident.py` (Incident ◆ SLAClock, WorkNotes, Resolution, Feedback; IncidentFactory with INC-YYYY-NNNN IDs); `domain/states.py` (IncidentState ABC + 10 states + registry); `domain/events.py` (events, EventBus); `scripts/gen_state_diagram.py` | 100-pair matrix: 20 pass, 80 raise; `test_BR04_*`; events emitted; state diagram generated from the registry | FN, DA, TST |
| P1.4 | Priority | M1 | P1.3 | `domain/priority.py` (PriorityStrategy ABC; WeightedProduct, Matrix; category floor; audited override) | `test_BR05_*`: all 27 combinations give the counts 4/6/10/7; floors; an override with no reason raises | FN, TST |
| P1.5 | SLA | M2 | P1.3 | `domain/sla.py` (§5.2 table ×1/×2/×4; PolicyBook with MissingSLAConfigurationError and a default; SLAClock with pause, resume, stop and reopen; SLAStatus; RiskEstimator ABC with the 75 % rule) | `test_BR07_*`: exactly 75 % → AT_RISK; at the deadline not breached, deadline + 1 µs breached; paused time and RESOLVED time excluded; missing policy | FN, TST |
| P1.6 | Assignment | M2 | P1.2 | `domain/assignment.py` (`select()` template calling `rank()`; Skill, Load and Smart strategies; CandidateScore with reasons; registry; costs 4/3/2/1; L_max 10) | `test_BR06_*`: load 10 accepted, 11 rejected; unavailable technicians excluded; TechnicianUnavailableError; Smart scores equal hand-computed values; runtime switch | FN, IN, TST |
| P1.7 | Escalation | M2 | P1.5 | `domain/escalation.py` (chain Technician → TeamLead → Admin → ITManager) | `test_BR08_*`: a P1 escalates just after 5, 10 and 15 min, not at exactly 5:00; P3 doesn't escalate on response; a resolution breach goes to the Team Lead | FN, IN, TST |
| P1.8 | Ports and in-memory repositories | M1 | P1.3 | `domain/repositories.py` (ABCs, UnitOfWork); `domain/ports.py` (AIAdvisor, EmbeddingProvider, NotificationChannel, IdentityVerifier); `domain/rule_advisor.py`; `repositories/memory.py` | A repository contract suite, reused for SQL in P2, passes on memory | DA, TD |
| P1.9 | Phase close | all | – | – | Domain coverage ≥ 90 %; review; PR | – |

## P2 Persistence, services, API — Fri 6 – Sat 7 Nov
| ID | Package | Owner | Deps | Files | Acceptance | Rubric |
|---|---|---|---|---|---|---|
| P2.1 | ORM and migrations | M3 | P1 | `repositories/sqlalchemy/{models,mappers,repos}.py` (18 tables, indexes, `version`); `alembic/`; SQLite pragmas | Contract suite on SQLite and PostgreSQL; `alembic upgrade head` on both | FN, DA |
| P2.2 | Seed data | M2 | P2.1 | `app/seed/` (campus services and dependency graph, categories, skills, teams, a demo account per role, technicians, 300–500 historical incidents from a seeded RNG) | `make seed` is deterministic and idempotent; analytics are non-empty | FN, IN |
| P2.3 | Auth and security | M3 | P2.1 | `api/deps.py`, `services/auth_service.py`, `core/security.py` (Argon2, PyJWT, lockout); register (Employee only), login, /me; CORS | Fifth failure locks and FakeClock +15 min unlocks; 401 and 403; logins audited | FN, TD |
| P2.4 | IncidentService facade and audit | M1 | P2.1–3 | `services/incident_service.py`; `services/audit.py` (hash chain, head lock, verify); post-commit dispatcher | Audit written in the same transaction; concurrent edit → 409; a failed notification doesn't roll back; `test_BR02_*`, `test_BR03_*`, `test_BR10_*` | FN, DA, TST |
| P2.5 | Notifications | M1 | P2.4 | `services/notifications/` (InApp channel; SMTP email with console fallback; factory; §5.4 routing as data; 3 retries) | T-NOTIF recipients; retries; fallback when SMTP is unset | FN |
| P2.6 | API routers and errors | M3 | P2.4 | `api/routers/*.py`, `api/schemas/`, `api/errors.py` | Each ITSMError maps to its §8 code; no stack traces leak | FN, TD |
| P2.7 | Search and analytics | M3 | P2.6 | `services/search.py`, `services/analytics.py` (9 filters, free text, pagination, CSV; overview, workload, services, MTTA, MTTR, compliance, CSAT, reopen rate, trends) | T-SEARCH: each filter alone and combined; paging boundaries; CSV | FN |
| P2.8 | SLA monitor | M2 | P2.4 | `services/sla_monitor.py` (APScheduler; testable `tick()`; warns and breaches once; SLAViolation rows; escalation; 72 h auto-close) | Tick tests on FakeClock; idempotent; `test_BR03_autoclose` | FN, IN |
| P2.9 | Authorisation matrix and client | M3, M4 | P2.6–8 | `tests/integration/test_authz_matrix.py`; regenerated TS client | Every role × endpoint; 403 on another user's incident; both databases | TST, FN |
| P2.10 | Hosting research | M3 | – | Proposal in PROGRESS.md | 2–3 free-tier options with verified limits, so you can create accounts by Sun 8 | TD |
| P2.11 | Phase close | all | – | – | Review; PR; CI green | – |

## P3 Frontend MVP and first deployment — Sun 8 – Tue 10 Nov
| ID | Package | Owner | Deps | Files (`frontend/src/…`) | Acceptance | Rubric |
|---|---|---|---|---|---|---|
| P3.1 | Design system and shell | M4 | P2.9 | `components/` (Badge, SLAChip countdown, ConfidenceBadge, Table, FilterBar, Empty, Error and Skeleton states, Toasts, NotificationBell, Modal); three distinct portal themes; login and register; role-routed navigation | Vitest per component; each role's nav reaches every one of its screens | UX |
| P3.2 | Employee portal | M4 | P3.1 | `pages/employee/` (report form with plain-language questions and an AI suggestion showing confidence, with override; my incidents; timeline; add info; respond; view resolution; verify or reject and rate) | Vitest; Playwright WF1 | FN, UX |
| P3.3 | Technician portal | M4 | P3.1 | `pages/technician/` (queue, plus team queue for a TeamLead; workload; acknowledge; start; notes; request info; hold; resolve; reassign) | Playwright WF2 | FN, UX |
| P3.4 | Admin configuration screens | M1 | P3.1 | `pages/admin/config/` (categories, services and dependencies, SLA grid, strategy and weights) | A new category takes effect live; Vitest | FN, UX |
| P3.5 | Admin operations screens | M3 | P3.1 | `pages/admin/` (users and technicians, 9-filter search with CSV, SLA violations, audit log with integrity check, Recharts dashboards) | Vitest; integrity check fails after deliberate tampering in a test | FN, UX |
| P3.6 | First deployment | M3 | P2.10 + accounts | Deploy config; migrate on deploy; auto-deploy main | Deployed URL serves login; WF1 works by hand | TD, IN |
| P3.7 | Phase close | all | – | – | Playwright WF1 and WF2 green; review; PR. Tue 10: dry run 1 | – |

## P4 Intelligence and integrations — Wed 11 – Sat 14 Nov
Never-cut work and WF3 come first; the cuttable extras follow in reverse cut order.
| ID | Package | Owner | Deps | Files | Acceptance | Rubric |
|---|---|---|---|---|---|---|
| P4.1 | Embeddings and duplicates | M2 | P3 | `domain/similarity.py` (TF-IDF, hybrid score); `adapters/gemini_embeddings.py` (provider-tagged vectors); `scripts/tune_duplicates.py`; `tests/fixtures/duplicate_pairs.json` (~50 labelled pairs); while-typing endpoint and UI hint; confirm-duplicate flow; 409 with link | `test_BR09_*`; INC101–103 linked; precision, recall and F1 in `docs/testing/duplicates.md` | IN, TST |
| P4.2 | Correlation and root-cause hint | M2 | P4.1 | `domain/dependency_graph.py` (BFS over depends_on); hint on incident detail ("likely related to INC-…, possible root cause") | Fee Portal → Database hint; transitive cases; no false hint for a closed P1 | IN |
| P4.3 | WF3 end to end | M4 | P4.1–2, P2.8 | `e2e/wf3.spec.ts` (3 payment tickets → duplicates linked → correlation → escalation, on the fake clock) | WF3 green in Playwright with fakes | FN, TST |
| P4.4 | Gemini advisor | M2 | P3 | `adapters/gemini_advisor.py` (google-genai, JSON schema, timeout, 1 retry, delimited text); FallbackAdvisor; model names in .env; decisions audited | Fake outage falls back to rules; malformed JSON rejected; `live` tests skipped in CI | IN, TD |
| P4.5 | Predictive SLA risk | M2 | P2.8 | `domain/risk.py` HistoricalRiskEstimator (§6.3, fallback below 10 samples); plain-words reason; UI risk chip | Estimate rises with elapsed time; fallback threshold | IN |
| P4.6 | SmartStrategy reasons in the UI | M4 | P3 | Assignment panel showing the top 3 with reasons | Playwright asserts the reason text | IN, UX |
| P4.7 | Suggested resolution | M2 | P4.1, P4.4 | `services/resolution_advisor.py` (top 3 similar resolved incidents; summary may cite only those IDs) | Citations ⊆ retrieved IDs; without Gemini, the list shows with no summary | IN |
| P4.8 | WebSockets | M3, M4 | P3 | `api/ws.py` (JWT; post-commit push); `hooks/useLive.ts` (reconnect; offline banner) | Live bell and dashboard update | IN, TD |
| P4.9 | Telegram alerts *(cut 6th)* | M1 | P2.5 | `adapters/telegram.py`; chat-ID linking in the profile; P1 and P2 routing | Fake Bot API; a send failure doesn't block | TD, IN |
| P4.10 | Google Sign-In *(cut 5th)* | M3 | P2.3 | GIS button; `adapters/google_identity.py` (`hd` check; first sign-in creates an Employee) | Wrong `hd` → 401 (faked verifier) | TD |
| P4.11 | Health map *(cut 4th)* | M4 | P4.2 | `pages/admin/HealthMap.tsx` (React Flow, coloured by open P1 and P2) | Vitest renders the nodes and edges | IN, UX |
| P4.12 | Voice input *(cut 2nd)* | M4 | P3.2 | Mic button using the Web Speech API, hidden when unsupported | Vitest with mocked SpeechRecognition | IN |
| P4.13 | Stretch: Telegram /report chatbot *(cut 1st)* | M1 | P4.9 | – | Only if ahead | IN |
| P4.14 | Phase close | all | – | – | Every feature degrades with its service off; review; PR. Sun 15: dry run 2 | – |

## P5 Hardening — Sun 15 – Mon 16 Nov (feature freeze at end of Mon 16)
- **P5.1 (M3)** Production settings and secrets on the host; HTTPS; CORS locked to the frontend's origin. Acceptance: deployed health check and a WF1 smoke test pass.
- **P5.2 (M3, cut 3rd)** Locust: 10k incidents, search p95 ≤ 300 ms; results in `docs/testing/performance.md`.
- **P5.3 (M1, M2)** Coverage ≥ 80 % on domain and services, enforced with `--cov-fail-under`.
- **P5.4 (M4)** All three workflows in Playwright, run by `e2e.yml` on PRs labelled `e2e`.
- **P5.5 (M2, M3)** `make demo-reset`, locally and on the deployment: reseed, ×10 clock, staged incidents per workflow.
- **P5.6 (M4)** UX pass: responsive layout, accessibility labels, empty and error states, PWA manifest.

## P6 Documentation and demo — Tue 17 – Wed 18 Nov
- **P6.1 (M1 UML, M3 architecture and ER)** PlantUML in `docs/diagrams/`: use case; class; state (generated); one sequence per workflow; architecture; ER (`scripts/gen_er.py` from SQLAlchemy metadata); deployment. All rendered by `make diagrams`.
- **P6.2 (owners per §15)** Report chapters 1–8, plus security, generated OOP and pattern evidence with file paths (`scripts/gen_pattern_table.py`), team responsibilities and a statement of AI use. Versions come from the lock files.
- **P6.3 (M4)** ≥ 15 cases in `docs/testing/cases.yaml`, mapped to pytest node IDs. `scripts/test_report.py` writes actual results from a real run into `report/generated/`. The traceability matrix is generated from `@pytest.mark.req("BR-xx")` markers.
- **P6.4 (M3)** Final README: one-command setup, Windows-native commands (uv, npm, SQLite, `scripts/dev.py`), demo accounts, architecture, tests, screenshots.
- **P6.5 (M4, all)** `docs/DEMO_SCRIPT.md`: shot by shot with timings per member (§14), plus the file name `15_OOP_S1_2025-2026_Project`, pending the IC.
- Chapters 1, 2 and 5 are drafted early whenever usage is spare. Drafts due Wed 18; recording Thu 19 – Fri 20; submission Sat 21.

## Usage rules
- Narrow tests while iterating, and `make verify` before each commit, as the gate between PRs.
- Playwright only at phase ends. Short command output.
- If usage runs short, cut in this order and log each cut: Telegram /report chatbot → voice input → Locust run → health map → Google Sign-In → Telegram alerts.
- Never cut: the MVP, core-rule tests, AI classification with its fallback, duplicates, smart assignment, escalation or predictive SLA.

## Needs a human (seeded into PROGRESS.md)
1. Confirm the file-name year (2025-2026 vs 2026-2027) with the IC.
2. Paste `scripts/cloud-setup.sh` into the cloud environment's setup script. The network policy must allow PyPI, npm, GitHub and the tectonic, plantuml and gitleaks downloads, and later generativelanguage.googleapis.com and api.telegram.org.
3. Gemini API key and model names; SMTP app password; Telegram bot token; Google OAuth client ID and campus domain. These go into deployment secrets only.
4. Hosting accounts after P2.10. Optional: branch protection, if you upgrade to GitHub Pro.
5. Review the ~50 labelled duplicate pairs (P4.1), run the dry runs, and merge each phase PR.

## Verification
- Every commit: `make verify` (Ruff, mypy --strict, import-linter, pytest with coverage, ESLint, tsc, Vitest) plus gitleaks via pre-commit.
- Every PR: CI green on SQLite and PostgreSQL; the report workflow when its paths change; E2E once the phase-end PR is labelled `e2e`.
- Phase end: that phase's Playwright workflows, a fresh-subagent review with findings fixed, PROGRESS.md updated, PR opened, and five bullets per module.
- P0: on a fresh clone, `make setup && make verify` passes; `make dev` serves `/health` and the placeholder UI; CI is green on the P0 PR.
