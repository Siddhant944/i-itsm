# Decisions and deviations

Every agreed deviation from docs/blueprint.md, and every interpretation where the sources were silent, with its reason.
The requirements PDF (docs/source/OOP_S1_2026-2027_Project.pdf) wins every conflict.

| ID | Date | Decision | Reason | Blueprint ref |
|---|---|---|---|---|
| D-001 | 3 Nov | Each phase runs in a fresh cloud session on the `claude/*` branch that session is given, cut from main after the previous phase PR merges. P0 uses `claude/funny-fermi-bjxlhr`. AGENTS.md updated to match. | A cloud session may push only to its assigned branch; fresh sessions also keep context (usage) small. | AGENTS.md sessions |
| D-002 | 3 Nov | SmartStrategy's required skills S_r = the category's required skill ∪ the service's optional `required_skill_id` (one extra column on `services`; still 18 tables). | §3 gives a category one skill, but §5.3's "2/2 skills" needs a set. | §3, §5.3, §9 |
| D-003 | 3 Nov | The SLA monitor ticks every 30 s of *clock* time; under AcceleratedClock ×10 it runs every 3 real seconds. | So P1 escalation at 5/10/15 min shows at 30/60/90 real seconds in the demo. | §5.2, §5.5, §14 |
| D-004 | 3 Nov | "Team Lead" is the lead of the assignee's team; for an unassigned incident, the lead of the team best covering S_r, else the Service Desk team. | The blueprint does not say which Team Lead. | §5.3, §5.5 |
| D-005 | 3 Nov | A confirmed duplicate's reporter is "subscribed to the parent" through the cancelled child's `parent_id`; no subscription table. | Keeps the 18-table schema. | §6.2, §9 |
| D-006 | 3 Nov | The reporter's reply to an info request resumes ON_HOLD → IN_PROGRESS, audited with the reporter as actor; technicians can also resume manually. | Workflow 2 shows "request info → reply" without a manual resume step. | §4, §14 |
| D-007 | 3 Nov | Added tools: import-linter (layer contracts in `make verify`), TanStack Query, openapi-typescript + openapi-fetch (generated client), a pure-Python TF-IDF, tectonic (report, locally and in CI), plantuml.jar (diagrams). | Enforce §2 mechanically; typed client; no heavy ML dependency; one TeX engine. | §2, §6.2, §12 |
| D-008 | 3 Nov | Self-registration is open to any email unless `ALLOWED_EMAIL_DOMAINS` is set; Google Sign-In always checks `hd`. | The requirements need Employee register/login; the blueprint restricts only Google sign-in. | §8 |
| D-009 | 3 Nov | A clock-control endpoint (`/dev/clock`) exists only when `APP_ENV` is `test` or `demo`. | Playwright and the demo need to move time deterministically. | §5.2, §14 |
| D-010 | 3 Nov | CI runs only on PRs, pushes to main and manual runs, cancels superseded runs, caches uv and npm. The report workflow runs only when its paths change; Playwright runs only on PRs labelled `e2e` (added at phase end) or by hand, because a `paths:` filter on pull_request events matches the whole PR diff and would re-run it on every push. `make verify` is the gate between PRs. | Private repo: 2,000 Actions minutes a month. | — |
| D-011 | 3 Nov | gitleaks runs in pre-commit and CI instead of relying on GitHub secret scanning; branch protection is optional. | Secret scanning and branch protection may need paid plans on a private repo. | §8 |
| D-012 | 3 Nov | No CODEOWNERS file (ownership lives in docs/PLAN.md); the four lost blueprint diagrams are not redrawn (AGENTS.md restates them; P6 generates the real ones from code); one cross-platform `scripts/dev.py` instead of per-OS scripts. | Save usage; the team reviews together. | §2 |
| D-013 | 4 Nov | External-service adapters live in `backend/app/adapters/`, with the same dependency rule as `repositories/` (domain and core only). The composition root `app/main.py` is the only module that imports every layer. | §2 names no package for adapters; this keeps services free of SDKs. | §2 |
| D-014 | 4 Nov | Helper tools install from reachable mirrors: gitleaks built from proxy.golang.org, PlantUML from Maven Central, tectonic from conda-forge via micromamba (`scripts/cloud-setup.sh`). Git hooks are local (`language: system`) so pre-commit needs no hook downloads. | GitHub release downloads are blocked in the cloud sandbox. | — |
| D-015 | 4 Nov | TypeScript pinned to 5.9.3 and @playwright/test to 1.63.0. | openapi-typescript needs TS 5.x and typescript-eslint needs < 6.1; Playwright must match the browser preinstalled in cloud sessions. | §12 |
