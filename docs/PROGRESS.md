# Progress

Updated at the end of every session. Plan: docs/PLAN.md · Decisions: docs/DECISIONS.md.

## Status: P0 Foundations, in review (4 Nov)

### Done
- P0.1 Sources moved to `docs/source/` and `docs/blueprint.md`; PLAN, PROGRESS and DECISIONS created; AGENTS.md session rules updated (D-001).
- P0.2 Backend skeleton: FastAPI app factory, `/health` with a database probe, typed settings, SQLite pragmas, Ruff, mypy --strict, pytest-cov and six import-linter layer contracts.
- P0.3 Frontend skeleton: Vite, React 19, strict TS, Tailwind 4, TanStack Query, generated OpenAPI client, placeholder health page with loading, error and success states; Playwright smoke test.
- P0.4 Tooling: `scripts/dev.py` (cross-platform) behind the Makefile, local pre-commit hooks with gitleaks, Docker Compose (api, web, postgres), `.env.example`, `.claude/settings.json`, `scripts/cloud-setup.sh`, LaTeX report skeleton built with tectonic.
- P0.6 Fresh clone `make setup && make verify` passes; `make dev`, `make e2e`, `make report` and `docker compose up` (api healthy on PostgreSQL, web on :8080) checked by hand; subagent review: 8 findings, all fixed (empty-secret handling, Windows line endings and process cleanup, cloud-setup repo detection, exact version pins, a Ruff ban on wall-clock calls).
- P0.5 CI: `ci.yml` (gitleaks; backend on SQLite and PostgreSQL; frontend and client freshness), `e2e.yml` (only on PRs labelled `e2e`), `report.yml`; issue and PR templates.

- Early report drafts (P6.2): chapters 1 Problem analysis, 2 Requirements (FR-01 to FR-31, NFR-01 to NFR-10, roles, BR-01 to BR-10) and 5 Technology stack with the nine answers. Draft 1, for the owners (M1, M2) to review; Chapter 5 versions are regenerated from the lock files at freeze.

### Next
- P1 Domain core (new session, branch from main after the P0 PR merges): P1.1 Clock and errors first.

### Needs a human
1. Create a repository label named `e2e` (Issues → Labels → New label) and add it to each phase-end PR so Playwright runs in CI. Merge the P0 PR once CI is green.
2. Paste `scripts/cloud-setup.sh` into the cloud environment's setup script. The network policy must allow PyPI, npm, proxy.golang.org, repo1.maven.org and conda.anaconda.org (later also generativelanguage.googleapis.com and api.telegram.org).
3. Confirm the video file-name year (`15_OOP_S1_2025-2026_Project` vs 2026-2027) with the IC.
4. Before P4: Gemini API key and model names (Google AI Studio). Before P4/P5: SMTP app password, Telegram bot token, Google OAuth client ID and campus domain. These go into deployment secrets, never the repo.
5. After P2.10: create the hosting accounts we propose. Optional: branch protection on main (needs GitHub Pro for a private repo).
6. P4.1: review the ~50 labelled duplicate pairs.
