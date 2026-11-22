# Progress

Updated at the end of every session. Plan: docs/PLAN.md · Decisions: docs/DECISIONS.md.

## Status: submission package ready (22 Nov, branch `ccr-95de7181-86g84a`)

### Done
- **Video reviewed** (`15_OOP_S1_2026-27.mp4` in Drive, 16 min 08 s, 4K, burned-in captions,
  read by OCR): all four members introduce themselves (Tushar 00:07, Shri Krishna 05:18, Ishaan
  08:03, Siddhant 11:35). Workflow 2 stops before resolution; the team chose to submit as is, and
  the report says so and points to `e2e/tests/wf2.spec.ts`.
- **Chapter 12:** the `TEAM:` placeholders are replaced by *What each member did*, built from the
  work-package owners in PLAN.md and the video.
- **Report:** new Chapter 13 *Project Demonstration* (timeline, the three workflows against the
  brief, innovation features shown); Chapter 12's demo column and Chapter 11's video column match
  the recording; D-040 and D-043 described; decision count 45; cover shows the repository and
  the video file name. 64 pages.
- **`deliverables/`** (D-045, `make deliverables`): one numbered folder per item of the brief's
  Deliverables list with the chapter as its own PDF, diagrams as SVG and PNG, the PostgreSQL
  schema, the test report and cases, plus the full report
  `15_OOP_S1_2026-2027_Project_Report.pdf`.
- **Accuracy pass (after PR #16):** report checked against the code and seeded data. Fixed: the
  Fee Payment example's category, the seed size, FR-13 (category only), the AT\_RISK rule
  (75 % status vs the predictive chip, D-032), the timeline (three weeks), where ownership is
  checked, where exceptions are caught, and Chapter 11's "Shown in" column. Chapter 13 now shows
  seven screenshots of the three portals. README: frontend test count, `make deliverables`.
- File names use 2026-2027 (D-045). Test report refreshed (24/24 cases pass; 1146 backend tests).
- `make report` falls back to XeLaTeX (`REPORT_ENGINE=xelatex`) when tectonic cannot download
  its bundle.

### Needs a human (today, 22 Nov)
1. Fix the auto-caption errors in the video (see the session notes: 00:25, 00:56-00:58, 11:32,
   15:31-15:37) if time allows.
2. Rename the video to `15_OOP_S1_2026-2027_Project.mp4` and upload it and
   `deliverables/15_OOP_S1_2026-2027_Project_Report.pdf` to the course's shared folder.
3. Merge the branch, then paste the repository link into the course spreadsheet.

## Previous: one-take recording ready (21 Nov, PR on `claude/bold-goodall-a5b7rd`)

### Done
- `make demo-reset` prints **WHO GETS WHAT IN THE TAKE**: the script's live reports replayed on the fresh data in a rolled-back transaction, with every assignee and escalation owner and their sign-in emails; `make demo-check` prints the same on the running demo and warns about reports made since the reset (D-043).
- Email and Telegram are delivered by a background worker, so Submit returns at once (D-043).
- The bell names each incident and shows the real time it arrived, converted back from the ×10 clock (D-044).
- Sign-ins on the demo last about 2.4 real hours (D-042).
- `docs/VIDEO_SCRIPT.pdf`: the word-for-word, one-take, 6-tab script, tested end to end in the sandbox at 1× speed (every step passed).
- CI fix: the rehearsal tests run before the first-start test that reseeds the shared PostgreSQL test database.

`make verify` passes: 1,146 backend tests (3 skipped), 142 frontend tests.

### Needs a human
- Record the take with the keys in the laptop's `.env` (Gemini, Google Sign-In, Gmail SMTP, Telegram on Rahul Verma's account), name the file `15_OOP_S1_2025-2026_Project` (confirm the year with the IC) and upload it with the report by 22 Nov.

## Previous: UI polish from an ITSM benchmark (13 Nov, after the restored features)

On `claude/nifty-maxwell-qkmfor`, fast-forwarded to `main` after PR #10 merged. We compared our
portals with the ITSM products of Salesforce, ServiceNow and Atlassian and closed the cheap gaps
it found, frontend only, in order of value for the UX criterion and the demo:
- **My queue opens on open work.** Verified, closed and cancelled incidents hide behind a "Show
  finished incidents (n …)" checkbox; RESOLVED stays, as in the team queue.
- **Sortable lists.** Every IncidentTable header sorts (ascending, descending, back to the page's
  order) with `aria-sort`; "SLA" sorts by the running clock's deadline, stopped or paused last.
  Admin search keeps its server-side sort because it pages.
- **Key facts under the incident title:** assignee, service, respond-by (or when the response
  came) and resolve-by. They left the Details card.
- **Skip link** (WCAG 2.4.1) on every portal page.
- **Light and dark themes for all three portals (D-040).** A Light/Dark/System switch in each
  portal's header, remembered per portal. Each portal keeps its own layout, navigation colour and
  accent in both themes, and opens in its usual theme until someone picks. All colour literals
  became semantic tokens (status colours included, charts and the health map too).
  `src/theme.test.ts` checks every text pair at 4.5:1 or more in all six combinations, and the
  axe-core e2e run now covers every screen in both themes. README shows three new screenshots.

`make verify` passes (1,137 backend tests, 3 skipped; 141 frontend tests). `make e2e`: all specs pass, the accessibility spec in both themes.

**Ready to record (16 Nov).** Same branch, three more things:
- **demo-reset settles the old outages (D-041)**, so the health map opens all green and
  Workflow 3's database outage turns it red on camera.
- **A rehearsal** (`e2e/demo/`, `cd e2e && npx playwright test -c demo` against a running
  `make demo-reset`) walks shots 4–9 on the real ×10 clock. It passes: the staged incidents, the
  duplicate hint and AI suggestion, the P1 and its assignment, follow-instead, the duplicate,
  the root-cause hint, the health map, escalations at 33, 63 and 94 s, the admin tour (category
  added live, audit chain intact) and Workflow 2 to closure.
- **DEMO_SCRIPT.md** now has the machine set-up, the rehearsal, the checklist items, a note that
  Workflow 1's P1 escalates too, and optional cues for SLA sorting and the theme switch.
  `make report` builds the 60-page PDF for shot 2.

`make verify` passes (backend and 141 frontend tests); `make e2e`: all 12 specs pass.

### Needs a human
1. **Review and merge the PR** for this branch; Render then redeploys `main` with the new screens.
2. **On the recording machine:** pull `main`, `make setup`, delete `.env.local` if it exists,
   allow the microphone, run the rehearsal, then `make demo-reset` before each take
   (DEMO_SCRIPT.md, "Before recording").
3. **Confirm the video file-name year** (`15_OOP_S1_2025-2026_Project`) with the IC.
4. **Confirm D-038, D-040 and D-041** (or ask for changes).
5. Before submission, not recording: chapter 12's two `TEAM:` notes
   (`report/chapters/12-team-and-ai.tex`), each owner's read of their chapters, and the report
   could mention D-040 and D-041.

## Previous: innovation features restored (13 Nov, after P6)

On `claude/awesome-fermi-lx7q8c`, fast-forwarded to `main` after the P6 PR (#9) merged. Three
items cut on 11 Nov are back (D-039), each named in the brief's Innovation Challenge list, each
with tests, a report entry and a demo shot:
- **Voice input (P4.12).** "Describe it by voice" on the report form and in the chat, using the
  browser's Web Speech API; hidden where unsupported.
- **Live service health map (P4.11).** Admin → Service health: React Flow map plus an
  accessible table; `GET /reports/service-health`; refreshed by live pushes.
- **Chatbot reporting (P4.13, in-app).** Employee → Report by chat: one question at a time,
  look-alikes to follow, the AI category with its confidence, filed through `POST /incidents`.
- Chapter 11 now maps all sixteen Innovation Challenge items (fifteen implemented).
- `make verify` passes (1,136 backend, 117 frontend tests); Playwright passes all 9 specs and the
  accessibility scan now covers 18 screens.

Also on 13 Nov: the deployment is live on Render with Neon in Oregon (same region as the API);
the app reads Neon's `.env.local` and accepts plain `postgresql://` URLs.

### Needs a human
1. Merge this branch's PR so Render redeploys `main` with the new screens.
2. **Local `.env.local` points at the production database.** Anyone who runs `neon init` gets
   it, and `make dev`, `make seed` and `make migrate` then use Neon, not SQLite. `make
   demo-reset` refuses, as it should. For local work, delete `.env.local` or run with
   `DATABASE_URL=sqlite:///./itsm.db`.
3. The seeded history leaves several old P1s open, so the health map starts with five services
   red. Fine for evaluation; for a cleaner Workflow 3 shot, say so and the seed can close them.

## Previous: P6 Documentation and demo (merged 13 Nov, PR #9)

On `claude/awesome-fermi-lx7q8c`, cut from main after the P5 PR merged. Every P6 package is done
and the phase review's findings are fixed. `make verify` passes: 1,128 backend tests (3 skipped by
design, 97 % coverage) and 106 frontend tests; Playwright passes all 9 specs (`make e2e`).
`make report` builds the 59-page PDF.

### Done
- **P6.1 Diagrams.** `make diagrams` regenerates and renders everything; Java is the only
  requirement (PlantUML's built-in smetana layout, no Graphviz). The state diagram, six class
  diagrams and the ER diagram are *generated from the code* by `backend/scripts/gen_diagrams.py`
  (State triggers, class members and bases, SQLAlchemy metadata); a test fails when a committed
  one is stale. Use case, architecture, deployment and one sequence diagram per workflow are
  hand-written. Index: `docs/diagrams/README.md`.
- **P6.3 Test cases.** `docs/testing/cases.yaml`: 23 cases across the six categories of the
  requirements, each naming its pytest tests. `make test-report` runs the suites once and
  writes each case's actual result and status, totals, coverage, per-suite counts and the
  BR-01..BR-10 traceability matrix into `report/generated/` and `docs/testing/test-report.md`.
  It refuses to report a run that did not finish.
- **P6.2 Report.** Chapters 3–12 written (architecture, UML, repository, database, testing,
  security, OOP and patterns, traceability, team and AI use). The pattern table and OOP evidence
  are read from the code (`gen_pattern_table.py`), chapter 5's versions from the lock files
  (`gen_versions.py`); `make report` regenerates them. Chapters 1, 2 and 5 no longer describe the
  cut voice input, health map or load test.
- **P6.4 README** rewritten: features, one-command start (Linux, Windows, Docker), demo accounts,
  screenshots of the three portals (`docs/screenshots/`), commands, architecture, tests.
- **P6.5 `docs/DEMO_SCRIPT.md`:** a 17-minute shot list per member covering the three workflows
  on the ×10 clock, with setup, timings and a checklist.
- **Seed data:** each category now has its own fix texts, so the suggested-fix panel shows a
  Wi-Fi fix for a Wi-Fi ticket in the demo; the rest of the generated history is unchanged.
- **Bug [#8](https://github.com/Siddhant944/i-itsm/issues/8)** (found by the phase review):
  refused operations (403) were never on the audit trail, though §8 says they are. The record
  was rolled back with the request, and ownership refusals were never recorded. The request's
  unit of work now records and commits the refusal after rolling the request back; a
  regression test covers both kinds and the chain's integrity.

### Phase review
A fresh-context subagent reviewed the whole phase diff against the code and the requirements and
reported 16 findings. It confirmed every Deliverables item is present and no cut feature is
claimed. All 16 are fixed:
- **The audit bug above** (the only code bug).
- **Docs that said more than the code does.** Assignment filters on availability, activity and
  capacity, and skills only rank. Ownership is checked in the service, not a FastAPI dependency
  (D-038, *proposed*). Embeddings and violations have their own repositories. A missing SLA
  policy is audited, not alerted. There are eleven patterns, not nine. The monitor escalates
  directly. Technicians can override priority and link Telegram. The class diagram showed the
  test-only `EventBus`; it now shows `PostCommitDispatcher`.
- **Demo script.** The technician window now signs in as whoever the strategy picked.
  Workflow 3's P1 is reported just before its escalations are filmed (all three fire within
  about 90 real seconds).
- **Test report.** It no longer reuses a previous run's JSON and names the database it ran on.
- **Windows.** The README and chapter 6 now say that diagrams and the PDF need Java and
  tectonic, with the CI artifact as the alternative.

### Next
- Dry run 2 with `make demo-reset` and `docs/DEMO_SCRIPT.md`; adjust the shot list to taste.
- Each owner reads and edits their chapters (owners are in each chapter's header comment).
- Record Thu 19 – Fri 20; submit the PDF and video by Sat 21 (hard deadline 22 Nov).
- Restore cut items only if the team wants them, in D-027's reverse order.

### Needs a human
1. **Review and merge this PR.** Add the `e2e` and `report` labels so CI runs Playwright and
   builds the PDF (download it from the run's artifacts).
2. **Chapter 12, "How AI tools were used":** add, in your own words, what each of you did
   yourselves (marked `TEAM:` in `report/chapters/12-team-and-ai.tex`). Check the
   responsibilities table there too.
3. **Confirm D-038** (where the ownership check lives) or ask for it to be moved into a
   dependency. If you confirm it, reword AGENTS.md's Security line to match.
4. **Confirm the video file-name year** (`15_OOP_S1_2025-2026_Project`) with the IC.
5. Still open from P5: Render and Neon accounts and the deployment (docs/DEPLOY.md); keys
   (`GEMINI_*`, `TELEGRAM_BOT_TOKEN`, `GOOGLE_*`) on the host; review the 52 labelled duplicate
   pairs.

## Previous: P5 Hardening (merged 12 Nov, PR #7)

On `claude/gallant-darwin-vrgc1q`, cut from main after the P4 PR merged. Every P5 package still
in scope after D-027 is done (P5.2, the Locust run, stays cut), and the phase review's findings
are fixed. `make verify` passes: 1080 backend tests (97.4 % coverage, 98 % on domain and
services) and 106 frontend tests. Playwright passes 9 specs (`make e2e`): WF1 (2), WF2, WF3, live
updates, an accessibility check of every screen in the three portals, and the phone drawer.

**Four days ahead of the freeze.** P5 was planned for 15-16 Nov and finished on the 12th, so the
diagrams, the report and the demo script (P6) can start early, and the cut items can come back
in D-027's reverse order if the team wants them (health map first).

### Done
- **P5.5 `make demo-reset`** (D-036). Wipes the local database, migrates, seeds, then runs one
  SLA-monitor tick that notifies nobody, so the seeded history's 173 breaches, 62 escalations
  and 30 auto-closes are recorded before the recording rather than in the middle of it (the
  next tick does nothing; a test proves it). Then it stages two starting points through the
  normal service: a P4 Fee Payment Portal report from another employee, so Workflow 1's live
  report shows the "similar open incident" hint (scores 0.77 and 0.84 against θ 0.49 for two
  typical phrasings), and a P4 Wi-Fi incident in the demo technician's queue for Workflow 2.
  Workflow 3 is reported live, because a P1 staged in advance would escalate within 90 real
  seconds on the ×10 clock. Finally it serves both apps with `APP_ENV=demo` and the ×10 clock,
  without reload (a reload would restart the clock). It refuses to run with `APP_ENV=prod`.
- The deployment's first-start seed (`SEED_ON_START`) gets the same quiet catch-up, so the
  first live tick on a new deployment no longer notifies dozens of people about months-old
  breaches. `DEMO_RESET_ON_START=true` turns a deployment into a demo instance that resets
  on every start (docs/DEPLOY.md, "A demo instance").
- **P5.1 Production settings** (D-037). `render.yaml` now runs the API with `APP_ENV=prod`,
  which refuses a weak `JWT_SECRET`, a fake clock, and any `CORS_ORIGINS` that is not the web
  app's `https://` origin; the `/dev` routes do not exist. HTTPS is Render's. The deployment
  itself still waits for the accounts (Needs a human 2).
- **P5.3 Coverage gate.** `make test` and CI fail below 90 % overall and below 80 % on domain
  and services (now 97.4 % and 98 %).
- **P5.4 All three workflows in CI.** Already true since P4: `e2e.yml` runs every spec on PRs
  labelled `e2e`; it now also runs the accessibility spec.
- **P5.6 UX pass.** The technician and admin sidebars fold into a drawer below 1024 px (Menu
  button, Escape and any link close it); the employee bar gives its links a row of their own
  on a phone. Each screen is its own chunk: the first download drops from 865 kB to 340 kB and
  only admins fetch the dashboard's charts (405 kB). A PWA manifest and icons make it
  installable on a phone (no service worker, so nothing is cached). An axe-core spec opens all
  16 screens and fails on any serious or critical WCAG 2.1 A/AA problem; its first run found
  that wide tables could not be scrolled from the keyboard, now fixed.
- **Bug [#6](https://github.com/Siddhant944/i-itsm/issues/6)** (found while building the
  reset): the monitor tried to escalate NEW incidents, which §4 forbids, and logged a warning
  for each of them on every tick, every three real seconds in the demo. Fixed with a
  regression test.

### Phase review
A fresh-context subagent reviewed the whole phase diff and reported 8 findings: 3 confirmed by
running code, 5 from reading it. It also ran the reset twice on a real PostgreSQL 16 and
exercised every branch of the image's start command. All 8 are fixed, the code ones each with a
test that fails without the fix:
- **`make demo-reset` could wipe the production database.** It sets `APP_ENV=demo` itself, so
  the "never in prod" check could not fire. With the Neon URL in `.env` (DEPLOY.md hands it
  out for `make migrate`), it would have dropped every table. The reset now also refuses any
  database that is not SQLite or a local or Compose PostgreSQL, unless given
  `--allow-remote-database`, which only the image's opt-in `DEMO_RESET_ON_START` passes.
- **A redeploy broke open tabs.** With screens loaded on demand, a tab opened before a push to
  main asked for a chunk that no longer existed and got React Router's developer error page.
  It now reloads once to pick up the new build, and otherwise shows "This screen could not be
  opened" with a Reload button.
- **The drawer did not move focus.** Keyboard users had to Shift+Tab to reach its links, and
  Escape dropped focus to the page body. Focus now moves into the drawer and back to Menu, and
  the page behind it is inert. The jsdom test could not see this, so the accessibility spec now
  checks the drawer in a real browser at phone width.
- **`CORS_ORIGINS` with a trailing slash** (copied from the address bar) passed the prod check
  but never matches a browser's `Origin`, so every sign-in would fail. Origins must now be
  exactly `https://host[:port]`.
- **A failed first catch-up was never retried**, because the seed marker was already written.
  The catch-up now has a marker of its own. Its test now also runs on CI's PostgreSQL leg.
- **Docs:**
  - DEPLOY.md's step 2 contradicted the new prod check; it now has you enter the URLs up front.
  - The way back from a demo instance would have kept future-dated data; it now resets on the
    real clock first.
  - D-037 and DEPLOY.md now say plainly that the seeded admin password is public on the
    deployment and should be deactivated after the evaluation (Needs a human 2).

One finding is answered rather than changed: `DemoResetRefusedError` is a `ValueError` and not
an `ITSMError`. It is a command-line guard that never reaches the API, like the settings
validators, and the §8 hierarchy is pinned at exactly 8 groups and 14 specific errors.

### Next
- **P6 Documentation and demo** (planned 17-18 Nov; can start now): PlantUML diagrams
  (`make diagrams`), the report chapters, the test-case table generated from a real run, the
  final README with screenshots, and `docs/DEMO_SCRIPT.md`.
- Restore cut items only if the team wants them, in D-027's reverse order: health map (P4.11),
  then the Locust run (P5.2), voice input (P4.12), the Telegram /report bot (P4.13).

### Needs a human
1. **Review and merge this PR.** Add the `e2e` label so Playwright runs in CI.
2. **Create the Render and Neon accounts and deploy** (docs/DEPLOY.md). The deployment now
   needs `CORS_ORIGINS` set to the web app's https URL, or the API refuses to start. The seeded
   admin and manager accounts use the public demo password: deactivate them after the
   evaluation.
3. **Try `make demo-reset` before dry run 2** (15 Nov) and say whether the staged incidents
   suit the script; P6.5 writes the shot list around them.
4. Still open from P4: the keys (`GEMINI_*`, `TELEGRAM_BOT_TOKEN`, `GOOGLE_*`) on the host;
   re-tune θ once a Gemini key exists; confirm D-032 and D-028; review the 52 labelled
   duplicate pairs; confirm the video file-name year with the IC.

## Previous: P4 Intelligence and integrations (merged 12 Nov, PR #5)

On `claude/awesome-brahmagupta-65bn2j`, cut from main after the P3 PR merged. Every P4 package
still in scope after D-027 is done, and the phase review's findings are fixed. `make verify`
passes: 1058 backend tests and 104 frontend tests. Playwright passes WF1, WF2, the new WF3 and a live-update spec (`make e2e`, 5 specs).

**Back on plan, a day ahead of the freeze.** P4 was planned for 11-14 Nov and finished on the
12th. The feature freeze is on the 16th.

### Done
- **P4.1 Duplicates (BR-09, §6.2).** `domain/similarity.py` has the hybrid score
  0.6·cos + 0.25·same service + 0.15·e^(−Δt/2 h) over a pure-Python TF-IDF, or over Gemini
  embeddings when configured (stored per incident, tagged with their model; D-030).
  θ = 0.49 and θ-high = 0.89 maximise F1 on 52 hand-labelled pairs; `scripts/tune_duplicates.py`
  writes `docs/testing/duplicates.md` (F1 0.92 and 1.00; text alone at 60 % gets 0.68 and misses
  the brief's own INC101-INC103), and a test fails if the constants drift. While typing, the
  report form lists open look-alikes with their score and reasons and offers "Follow this
  instead"; the same reporter's near-identical report within 30 minutes is a 409 that links
  to the first; whoever works an incident sees possible duplicates and confirms one in two
  clicks. Followers see what their report is linked to (id, title, status: BR-01 still
  applies) and are told when it is resolved (D-005, D-031).
- **P4.2 Correlation (§6.2).** BFS over `depends_on` both ways. A live P1/P2 on a service an
  incident depends on is its possible root cause, nearest then most urgent then closest in
  time; staff see "Likely related to INC-… (Database Cluster): possible root cause." and the
  path of services, plus what an outage may be causing.
- **P4.3 Workflow 3 in Playwright.** A Database P1, then the brief's three payment tickets
  from three people: one submits anyway, one follows, the assignee confirms the duplicate,
  the admin sees two linked reports and the root cause, and moving the fake clock escalates
  the P1 to levels 1 and 2 (BR-08). It found a real ranking bug, fixed in P4.2.
- **P4.4 Gemini classifier (§6.1).** Prompt built from the live category list, ticket
  delimited as data, JSON schema, 8 s timeout and one retry, answer checked against the real
  category ids; `FallbackAdvisor` answers with the keyword rules on any outage or bad answer.
  Every AI classification is audited with its source and confidence.
- **P4.5 Predictive SLA risk (§6.3).** P(breach) = |T>R| / |T>e| over comparable resolved
  incidents, AT_RISK at 0.5, the 75 % rule below ten samples, with a plain-words reason. Staff
  see a chip; the stored SLA status keeps the 75 % rule (D-032, needs confirming).
- **P4.6** was done in P3: the top three technicians with reasons (WF1 asserts them).
- **P4.7 Suggested resolution (§6.1).** The three most similar resolved incidents; a Gemini
  summary that may cite only those ids (checked in its citation list and its text, refused
  otherwise). "Use this fix…" copies into the resolve box to edit; nothing is applied.
- **P4.8 WebSockets (§6.4).** `/ws`, token in the first message, pushes of an incident id and
  status only, after the commit, to the reporter, the assignee and leads and admins; the
  browser refetches through the API. Polling drops to 60 s while live and returns to 10 s,
  with a banner, while reconnecting (D-033; replaces D-024).
- **P4.9 Telegram alerts (§5.4).** Bot API adapter whose errors never carry the token;
  P1/P2 alerts to users who linked a chat ("Telegram alerts" in the user menu); a test
  message button (D-034).
- **P4.10 Google Sign-In (§8).** ID token checked against Google's keys, audience, issuer,
  expiry on the injected Clock and `email_verified`; `hd` must be the campus domain (D-008);
  the first sign-in creates an Employee, an existing account is linked by verified email
  and never to a second Google account (D-035).
- **Every feature degrades with its service off** (P4.14): no Gemini key → keyword rules,
  TF-IDF, a fix list without a summary; Gemini down or answering nonsense → the same, logged;
  no bot token → no Telegram channel; no Google settings → no button and a 503; socket down
  → polling. Each path has a test.
- Also fixed along the way: incident responses after an action now carry their duplicate
  links; `live` tests are actually skipped unless `RUN_LIVE_TESTS=1`.

### Phase review
A fresh-context subagent reviewed the whole phase diff and reported 11 findings, 7 of them
confirmed by running code. All are fixed, each with a test that fails without the fix:
- **The Telegram bot token reached the logs.** The adapter kept it out of its own errors, but
  httpx logs every request URL at INFO. httpx and httpcore now log warnings only.
- **Account squatting.** Anyone could self-register `victim@campus.edu` with a password; when
  the real owner later used Google, the accounts were linked and the squatter's password kept
  working. Linking to Google now drops the password (audited; D-035 amended).
- **Duplicates (D-031 amended):** a reporter was shown, and could follow, every match rather than
  three; a duplicate could be linked to an already resolved or closed parent; withdrawing a
  followed incident stranded its followers; a technician could link to, and so read the title
  of, any incident by guessing its id.
- **Google Sign-In under the ×10 demo clock** would have rejected fresh tokens after about seven
  real minutes; token expiry is now judged on the system clock.
- **WebSockets** outlived token expiry and deactivation; a socket now re-checks every 30 s.
- **Correlation** could lose the root cause under a flood of newer dependent incidents; the
  upstream P1/P2 query is now separate.
- Smaller: the summary prompt now delimits titles too; DECISIONS.md's table was broken by a
  blank line, so D-020 onwards rendered as plain text.

### Next
- **P5 Hardening** (15-16 Nov): production settings and CORS on the host (P5.1), coverage
  gate (P5.3), all three workflows in CI (P5.4), `make demo-reset` (P5.5, see below), UX pass
  (P5.6). Restore cut items only if time remains, in D-027's reverse order.
- For **P5.5**, still: the seeded history was never watched by the monitor, so the first tick
  after a seed records ~170 breaches and ~60 escalations at once (visible in the e2e log).
- For **P5.6**: sidebar portals below ~900 px, and splitting the bundle by portal.

### Needs a human
1. **Review and merge this PR.** Add the `e2e` label so Playwright runs in CI.
2. **Keys, for the features to run for real** (all go into the host's secrets, never the repo):
   `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_EMBEDDING_MODEL`; `TELEGRAM_BOT_TOKEN`;
   `GOOGLE_CLIENT_ID`, `GOOGLE_HD_DOMAIN` and `VITE_GOOGLE_CLIENT_ID`. Nothing has been tried
   against the real Gemini, Telegram or Google APIs yet. With a key, `RUN_LIVE_TESTS=1 make test`
   runs the live Gemini test.
3. **Re-tune θ with Gemini.** The thresholds are tuned for TF-IDF. Once a key exists, run
   `scripts/tune_duplicates.py` with the Gemini provider before the demo, or keep TF-IDF.
4. **Confirm D-032** (predictive risk shown on the incident; search, dashboard and monitor
   keep the 75 % rule) and **D-028** from P3 (any Team Lead may pick up an unassigned incident).
5. **Review the 52 labelled duplicate pairs** in `backend/tests/fixtures/duplicate_pairs.json`.
6. Still open from P3: create the Render and Neon accounts and deploy (docs/DEPLOY.md), dry
   run 2 on 15 Nov, and confirm the video file-name year with the IC.

## Previous: P3 Frontend MVP and first deployment (merged 11 Nov, PR #4)

On `claude/affectionate-mccarthy-txowq5`, cut from main after the P2 PR merged. All seven
packages are done and the phase review's findings are fixed (see P3.7 below).

`make verify` passes: 888 backend tests and 83 frontend tests. Playwright runs
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
  API, the audit chain verified) both pass.
  A fresh-context subagent then reviewed the whole phase diff and reported 16 findings, 9 of
  them confirmed by running the API. All but the two listed under "Known gaps" are fixed, each
  with a test that fails without the fix. The four that mattered most:
  - retiring a service made every further step on its open incidents a 404;
  - a technician holding open incidents, or a team's lead, could be deactivated, and an
    escalation owner demoted, leaving incidents with someone who could not open them;
  - an Administrator could demote, deactivate or create an IT Manager (D-029);
  - incidents "queued for a Team Lead" were invisible to every lead (D-028).

  Also fixed: `PATCH /users/{id}` was two transactions; the audit sequence was wrong under the
  incident filter; SLA target validation ran when stored rows were loaded; a retired category
  could still be chosen; retired services showed as "—" on older incidents; one failed
  10-second refresh replaced the page with an error and lost typed text; a category applied by
  the classifier was not announced to the reporter; a stale suggestion could be shown for new
  text; technicians had no list of what they reported; the incident page offered actions the
  API refuses; "SLA met" was shown for cancelled and late-response incidents; an API outage
  signed people out; the CSV download bypassed the generated client.
- **Known gaps, not fixed in P3.** (1) The timeline is built from what the incident itself
  returns, so it shows reports, notes, questions, answers, resolution, feedback and closure but
  not assignments, escalations or overrides; those are on the audit trail, which only admins
  see. (2) An administrator cancelling someone else's incident is recorded with the reason
  "withdrawn", because the domain has only "withdrawn" and "duplicate" until P4.1 confirms
  duplicates. Both are small and both belong with P4 work that touches the same code.
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
1. **P4 cuts are decided (D-027):** the Telegram /report chatbot, voice input, the health map
   and the Locust run are out for now; Telegram alerts and Google Sign-In stay. Two things
   follow for people rather than code: reword Workflow 1a in the demo script (no voice
   report), and P4.9 and P4.10 need a Telegram bot token, a Google OAuth client ID and the
   campus domain before those sessions start.
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
