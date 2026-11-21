# Demo runbook: the recording, click by click

> **For the final recording, follow `docs/VIDEO_SCRIPT.pdf`** (one take, 6 tabs, checked end to end on 21 Nov against `make demo-reset`, with a 1x walkthrough video). This file is an earlier guide and its tab layout and incident numbers differ.

A fixed sequence for the graded video (requirements §9: 15–20 minutes, every member on camera,
at least three complete workflows). It uses **three browser tabs**, a terminal and the report PDF.
It covers every MVP item, every role capability the brief lists, all seven intelligent features
and the Innovation Challenge items we built. The coverage table is at the end.

**Checked on 21 Nov 2026.** Two full dry runs on a fresh `make demo-reset` (no Gemini key, so
suggestions come "from keyword rules") produced the same IDs, assignees, escalation targets and
messages as written here. The values are deterministic because the seed is fixed and every
assignment depends only on the **order** of events, which the three rules below fix.
[DEMO_SCRIPT.md](DEMO_SCRIPT.md) stays the background reference (set-up detail, Telegram,
the ×10 clock table).

## The three timing rules

Everything else can go at speaking pace. The ×10 clock turns 1 real second into 10 clock seconds.

| Rule | Why |
|---|---|
| **R1.** Meera acknowledges INC-2026-0423 **within 25 s** of Submit. | A P1 must get a response within 5 clock minutes (30 real seconds), or it escalates. |
| **R2.** Anika's first report is submitted only **after** INC-2026-0423 shows *Escalated · level 1* (about **3:00** after Workflow 1's Submit). | The escalation moves the P1 from Meera to Rohit Khanna, which changes who the Smart strategy picks next. Doing it in this order gives the names below. |
| **R3.** INC-2026-0425 is confirmed as a duplicate **within 60 s** of submitting it. | It is a P2, so it escalates after 90 real seconds if left alone. |

Also: **don't acknowledge INC-2026-0426** (the database P1); its escalation is the point.
**Type the texts exactly as given and don't click "Use this suggestion"**: the text decides the
category, the category decides the required skill, and the skill decides the assignee.
Start a stopwatch at Workflow 1's Submit (**T = 0**). The Workflow 3 timings use a second one
(**D = 0** at the database report).

## Set-up (before the live take)

1. On the recording machine: pull `main`, run `make setup`, and delete `.env.local` if it exists.
   Use the same `.env` you will record with. **A Gemini key changes the category wording and
   confidence, and possibly the assignees.** With a key, do one silent run-through first and
   correct the names in this file.
2. Open `report/build/main.pdf` (`make report`) in a PDF viewer, not the browser. Open a terminal
   at the repository root.
3. **`make demo-reset`.** Wait for `API http://127.0.0.1:8000/health · web http://localhost:5173`.
   Check the printout says:
   - `staged for Workflow 1 … INC-2026-0421 P4 'Fee payment portal page is very slow' (assigned to user 13)`
   - `staged for Workflow 2 … INC-2026-0422 P4 'Wi-Fi keeps dropping in the library reading room' (assigned to user 2)`
4. One Chrome or Edge window at 100 % zoom, 1280×800 or larger, with **three tabs**. Type
   `localhost:5173` into each tab by hand. **Don't use "Duplicate tab"**: it copies the sign-in.
   Each tab holds its own sign-in. Move between them with Ctrl+1, Ctrl+2 and Ctrl+3.

   | Tab | Starts as | Signed in before the take? |
   |---|---|---|
   | **E**, Employee (Ctrl+1) | the sign-in page | No: the take starts with a failed sign-in. |
   | **T**, Technician (Ctrl+2) | **Meera Joshi**, `sys2@campus.edu`, on *My queue* | Yes |
   | **A**, Admin (Ctrl+3) | **Rahul Verma**, `admin@campus.edu`, on *Dashboard* | Yes |

   Every password is `demo1234`. The one new account made on camera uses `demo12345`.
5. Allow the microphone for `localhost:5173`; it is used in S43. Turn the laptop's notifications off.
6. Optional: Telegram on a phone in shot. After the reset, link (header → **Telegram alerts**)
   `sys2@` (Meera), `sys1@` (Rohit Khanna), `admin@`, `manager@`, `employee@` and `technician@`.
7. **Start the take within about 15 minutes of the reset.** The staged P4 ticket raises its own
   SLA warning about 18 minutes after the reset; that is harmless but distracting.

## Takes

| Take | Video time | Screen |
|---|---|---|
| 1. Introductions and design | 0:00–3:45 | Faces, then the report PDF |
| 2. Live application, **one continuous take** | 3:45–16:00 | The three tabs (plus the terminal and phone for notifications) |
| 3. Engineering evidence and close | 16:00–18:00 | Terminal, then tab T reused for GitHub |

---

## Take 1: introductions and design (0:00–3:45)

| # | Video | Who | Screen | Say / do |
|---|---|---|---|---|
| S1 | 0:00 | All | Title card, then each face | Name, ID, module: M1 Tushar, domain model and lifecycle; M2 Siddhant, intelligence and SLA; M3 Shri Krishna, platform, persistence and security; M4 Ishaan, frontend and QA. |
| S2 | 1:00 | M1 | PDF: use-case diagram | The problem (late responses, wrong priorities, duplicates, no history) and the stakeholders: Employee, Technician (Team Lead), Administrator (IT Manager). |
| S3 | 1:40 | M1 | PDF: class diagram | `User` (abstract) → Employee, Technician → TeamLead, Administrator → ITManager: inheritance only for *is-a*, with permissions from a role → permission map, never `isinstance`. The `Incident` aggregate owns its notes, SLA clock and resolution (composition); services and categories are associations. Private state behind read-only properties, changed only through methods such as `acknowledge(actor, clock)`. Value objects are frozen dataclasses. |
| S4 | 2:30 | M1 | PDF: state diagram | Ten states, **exactly 20 transitions** (State pattern). Every other move raises `InvalidStateTransitionError`; we prove it live in S45. The other patterns: Strategy (assignment, priority), Factory (incidents, notifications), Observer (domain events → audit and notifications), Repository, Adapter (Gemini, SMTP, Telegram, Google), Chain of Responsibility (escalation), Facade (`IncidentService`). |
| S5 | 3:05 | M3 | PDF: architecture and ER diagrams | Five layers with dependencies pointing inward, enforced in CI by import-linter. React + TypeScript → FastAPI → services → domain; SQLite locally, PostgreSQL in Docker, on Render and on Neon, both tested in CI. 18 tables; audit written in the same transaction as the change, notifications after commit. |

---

## Take 2: live application (3:45–16:00)

### Sign-in and portals (M4)

| # | Tab | Do (exactly) | You will see | Say |
|---|---|---|---|---|
| S6 | E | Email `employee@campus.edu`, Password `wrongpass` → **Sign in** | "That email and password did not sign you in. After five failed attempts an account is locked for 15 minutes." | Invalid login is handled; passwords are Argon2-hashed; JWT on every API call. |
| S7 | E | Password `demo1234` → **Sign in** | Employee portal, Devika Rao, nav: My incidents · Report an incident · Report by chat | Mention the Google sign-in button if `GOOGLE_CLIENT_ID` is set. |
| S8 | T, A | Ctrl+2, then Ctrl+3 | Technician portal (Meera: My queue · Workload) and Admin portal (dark sidebar, Operations and Configuration groups) | The three portals look different on purpose; each role's navigation links every screen it may use. |

### Workflow 1: employee reports → system prioritises → technician assigned → notified (M1 types, M2 explains)

| # | Tab | Do (exactly) | You will see | Say |
|---|---|---|---|---|
| S9 | E | **Report an incident**. One line: `Payment application unavailable`. What happened: `Users are unable to complete transactions: the fee payment portal fails at checkout for everyone.` Service: **Fee Payment Portal** | The suggestion card **"Suggested category: Payments · High confidence · 100% · from keyword rules · Use this suggestion"**, and **"This may already be reported"** with INC-2026-0421, "Fee payment portal page is very slow", **59% match** · text 33 % alike · same service · reported close together | The brief's own scenario. AI categorisation shows its confidence and is never applied silently (don't click it). Duplicate detection runs while typing; this look-alike is a different problem (slow, not down), so carry on. |
| S10 | E | Who is affected? **Many people or everyone**. Can you keep working? **I am blocked**. Click **Submit incident** and **start stopwatch T** | **INC-2026-0423 · Assigned · P1 Critical · Response due in 4m 48s**. Assigned to **Meera Joshi**; Respond by and Resolve by deadlines; Category Payments; **Priority score 27** | Impact 3 × urgency 3 × business criticality 3 (a Gold service) = 27 → P1. The Gold P1 SLA is 5 min to respond and 30 min to resolve; the deadlines are computed and stored. |
| S11 | T | Ctrl+2 (**before T+0:20**) | Bell count up by one; INC-2026-0423 on top of *My queue*, pushed live over the WebSocket | In-app notification plus live push. Email goes to the API console (or SMTP); Telegram goes to the phone if linked. |
| S12 | T | Click **INC-2026-0423** → **Acknowledge** (**by T+0:25**, R1) | Acknowledged · "Resolution due in 29m" · risk chip "On track (75 % rule)" | Response SLA met. Only the next legal actions are offered (Start work, …). |
| S13 | T | Click **My queue** in the sidebar | The queue, with INC-2026-0423 on it | Leave tab T here: in S20 you will watch the ticket leave this queue. |
| S14 | E | Ctrl+1. In **Add information**, type `The error code shown at checkout is PG-502.` → **Send** | The timeline gains "Information provided · Devika Rao" | The employee adds information after reporting. |
| S15 | A | Ctrl+3 → **Incidents** → Incident ID `INC-2026-0423` → **Apply filters** → click the row | The admin view of the incident | Admins see every panel: |
| S16 | A | Scroll to **Assignment** | "Ranked by the **Smart** strategy: 1. Rohit Khanna 0.85 (senior, 50 % capacity free, 15 past fixes), 2. Aditya Reddy 0.83, 3. **Meera Joshi — Current** 0.74" | Smart recommendation: 40 % skill, 30 % spare capacity, 15 % experience, 15 % past fixes on the service. When the ticket came in, Meera had 90 % capacity free and scored 0.86, just above Rohit; holding the P1 drops her to 0.74. Load balancing is working. Each row has **Assign** for a manual override (don't click it). |
| S17 | A | Scroll through **Suggested fix**, **Possible duplicates** and **Audit trail** | Suggested fix: INC-2026-0046 38 % similar, "Reconciled the failed transactions with the bank…". Possible duplicates: INC-2026-0421 59 %. Audit: Incident created · AI classified · duplicate suggested · priority assessed · state changed (classified, assigned) · state changed by Meera Joshi | Suggested resolution from history; the complete audit history (timestamp, user, action, from → to). |
| S18 | E | Ctrl+1 → **Report an incident**. Enter **exactly the same** title, text, service and answers as S9–S10 → **Submit incident** (about T+1:15) | "You reported this a few minutes ago. It is INC-2026-0423. Add anything new there instead of reporting it again." | The same reporter's near-identical repeat is refused (409, `DuplicateIncidentError`, BR-09). |

### Workflow 3: multiple reports → duplicates and related incidents → correlated and escalated (M2)

| # | Tab | Do (exactly) | You will see | Say |
|---|---|---|---|---|
| S19 | E | **Sign out** → **Create an account**. Full name `Neha Kapoor`, Email `neha.kapoor@campus.edu`, Password `demo12345` → submit | Signed straight into the Employee portal as Neha Kapoor | Self-registration creates an Employee account, so nobody can register as staff. |
| S20 | E | **Report an incident**. One line `Payment transaction failing`, What happened `My fee payment fails at the last step and the money is not taken.`, **Fee Payment Portal**, **Many people or everyone**, **I am blocked** | "This may already be reported": **INC-2026-0423, 63 % match** and INC-2026-0421, 56 % | A different reporter in different words is still matched by text, service and time. |
| S21 | E | On INC-2026-0423 click **Follow this instead** → **Follow INC-2026-0423** | INC-2026-0424 · Cancelled · "This is the same problem as INC-2026-0423 (Payment application unavailable)… we will tell you when it is fixed." Duplicate of INC-2026-0423 | No second ticket for the team; Neha is now subscribed to the original. |
| S22 | E | **Sign out** → sign in `anika.chopra@campus.edu` | Anika Chopra's portal | (Don't report yet: R2.) |
| S23 | A | Ctrl+3 → reload INC-2026-0423. **Wait for T ≈ 2:15 and T ≈ 3:00** | About T+2:15 the chip turns *At risk*, and Meera gets an *SLA approaching* notification (75 % of the resolution target). **About T+3:00**: "Resolution overdue · Breach risk 100% · **Escalated · level 1**", assigned to **Rohit Khanna**; this admin's bell shows "INC-2026-0423 has breached its SLA" | SLA monitoring runs in the background (APScheduler). A warning before the deadline; on a resolution breach the P1 goes straight to the assignee's **Team Lead** (BR-08). |
| S24 | T | Ctrl+2 → click **My queue** to refresh it | Meera's bell has gone up (the breach notice), and INC-2026-0423 is no longer in her queue | Ownership moved with the escalation. Live pushes go to the new owner, so the old queue needs this click. Meera can no longer open the incident (BR-01). |
| S25 | E | Ctrl+1 → **Report an incident**. `Unable to make payment` / `The payment application shows an error and my fee transaction does not complete.` / **Fee Payment Portal** / **Just me** / **I am blocked** → **Submit incident** anyway (**start a 60-second count**, R3) | The form showed INC-2026-0423 at 73 %. The new incident is **INC-2026-0425 · P2 High** (score 9), assigned to **Aditya Reddy** | Lower impact → P2. Anika ignored the hint; the system still catches it in S27. |
| S26 | E | In the address bar change the ID to `INC-2026-0422` and press Enter | "You may not view INC-2026-0422." | Role and ownership are checked on every route (BR-01, 403). |
| S27 | A | Ctrl+3 → **Incidents** → ID `INC-2026-0425` → **Apply filters** → open it. Under **Possible duplicates**, on INC-2026-0423 (73 %) click **Confirm duplicate…** → **Cancel INC-2026-0425 as its duplicate** (within R3's 60 s) | INC-2026-0425 · Cancelled · SLA stopped · "This is the same problem as INC-2026-0423" | Duplicate detection (offline TF-IDF, tuned threshold); a person confirms. INC-2026-0423 now says "2 other reports are linked to this incident as duplicates". |
| S28 | E | Ctrl+1 → **Report an incident**. `Database cluster not responding` / `Every query to the main database times out; nothing that uses it works.` / **Database Cluster** / **Many people or everyone** / **I am blocked** → **Submit incident** and **start stopwatch D** | **INC-2026-0426 · P1 Critical** · Category Database (100 %) · assigned to **Meera Joshi** | |
| S29 | T | Ctrl+2. **Don't touch anything** | INC-2026-0426 appears in Meera's queue | Nobody acknowledges it: watch what the system does. |
| S30 | A | Ctrl+3 → open **INC-2026-0423** (Incidents → ID) → **Related through services** | "**Likely related to INC-2026-0426 (Database Cluster): possible root cause.**" Fee Payment Portal → Database Cluster | Incident correlation through the service dependency graph: automated root-cause hint. |
| S31 | A | **Service health** | Map and table: Outage 2, Impacted by a dependency 5, Operational 7. Database Cluster and Fee Payment Portal red; red, moving arrows to Exam Portal, Hostel Management, LMS, Library Portal and Student Information System; the *Trouble comes from* column says Database Cluster | Live service dependency graph and real-time operational view. |
| S32 | A | Stay on the page and watch the bell | **D+0:30** level 1 → **Rohit Khanna** (Team Lead). **D+1:00** level 2 → **Rahul Verma**: this admin's bell goes up; click 🔔 to read "INC-2026-0426 has been escalated to you". **D+1:30** level 3 → **Sunita Iyer** (IT Manager) | Automatic escalation: Technician → Team Lead → Administrator → IT Manager (Chain of Responsibility). |
| S33 | A | **SLA violations** | INC-2026-0426 Response at risk and Response breached; INC-2026-0423 Resolution at risk and Resolution breached | Violations are recorded once each, with deadline and detection time. |
| S34 | A | Open **INC-2026-0426** | "Response overdue · **Breach risk 88%** · **Escalated · level 3**", assigned to Sunita Iyer. The audit trail shows 3 × Incident escalated and 2 × SLA violated. *Open incidents this may be causing* lists INC-2026-0423 and others | Predictive SLA risk: "88 % of past P1 Database incidents still open at 15 m went on to breach (15 of 17)". |

### Administration (M3)

| # | Tab | Do (exactly) | You will see | Say |
|---|---|---|---|---|
| S35 | A | **Categories** → **Add a category**. Name `Audio-Visual`, Required skill **hardware**, Keywords `projector, speaker, microphone, hdmi` → **Add category** | Toast: "Audio-Visual was added and is live for the next incident." | New categories without code changes (open/closed). |
| S36 | E | Ctrl+1 → **Report an incident**. One line `Projector in lecture hall 3 shows no signal`, What happened `The projector says no signal when I connect my laptop over HDMI.` **Don't submit** | "Suggested category: **Audio-Visual** · Medium confidence · 67%", and Audio-Visual is in the Category list | The classifier picked up the new category at once. Leave the page via **My incidents**. |
| S37 | A | Ctrl+3 → **Services** → **Edit** on Fee Payment Portal → look → **Cancel** | Criticality 3 · High, tier Gold, depends on Database Cluster, Identity Provider and Campus Network Core | Manage IT services: criticality drives priority, the tier picks the SLA, dependencies drive correlation. |
| S38 | A | **Users** → **Edit** on Arjun Menon → look → **Cancel** | Role, team, skills (networking, windows), experience; *Add a user* and *Deactivate* | Manage users and technicians. |
| S39 | A | **SLA policies**. In the **Bronze** column, P4 row, change the resolution box `5760` → `4320` → **Save** | Gold P1 shows 5 min / 30 min, as in the brief. Toast: "… saved. New incidents use it from now on." | Configurable SLA per service tier × priority; incidents already open keep their target. |
| S40 | A | **Assignment** → choose **Load based** → **Save assignment settings** → open INC-2026-0423 → **Assignment** card → back to **Assignment** → **Smart** → **Save assignment settings** | "Ranked by the **Load based** strategy": technicians with 100 % capacity free (Farhan Qureshi, Ananya Bose, Omar Baig), skills ignored | Three interchangeable strategies (Strategy pattern), switched at run time; the Smart weights are editable too. |
| S41 | A | **Incidents**: click the chips Priority **P1 Critical** and SLA status **Breached** → **Apply filters**. Add Status **Assigned** → **Apply filters**. Then Service **Database Cluster** → **Apply filters** → **Export CSV** | 47 incidents (history included), then 2 (INC-2026-0426 and INC-2026-0423), then INC-2026-0426 only; a CSV downloads | Twelve criteria: text, ID, date range, status, priority, SLA status, category, service, technician, reporter, sort and order. |
| S42 | A | **Audit log** → **Verify integrity**. Then Incident ID `INC-2026-0423` → **Filter** | "✓ … audit records verified; the chain is intact." Then that incident's full history | The audit log is append-only and hash-chained (BR-10), so tampering is detectable. |
| S42b | A | **Dashboard** (try 7 / 30 / 90 days). Switch the header theme to **Dark**, then back | Open, Critical open, At risk, Breached, Unassigned, MTTA, MTTR, SLA compliance, CSAT, Reopen rate; reported vs resolved per day; breaches by service; **Technician workload** and **Service analysis**, each with Export CSV | The incident overview, technician workload and service analysis reports from the brief, plus analytics. Light and dark themes. |

### Workflow 2: technician investigates → SLA monitored → resolved → user notified (M4)

| # | Tab | Do (exactly) | You will see | Say |
|---|---|---|---|---|
| S43a | T | Ctrl+2 → **Sign out** → `technician@campus.edu` (Arjun Menon). Click the **SLA** column header. Then **Workload** | My queue includes INC-2026-0422 "Wi-Fi keeps dropping in the library reading room", P4 Assigned. Workload: "Arjun Menon 2 / 10 … Available" | The technician's queue, sortable by SLA due; their current workload (P1–P4 weigh 4/3/2/1, cap 10). |
| S43b | E | Ctrl+1 → **Sign out** → `employee@campus.edu` (Devika) | My incidents lists INC-2026-0423 and INC-2026-0422 with their status | Employee views and tracks their incidents. |
| S43c | T | **My queue** → INC-2026-0422 → **Acknowledge** → **Start work** | Acknowledged, then In progress | ASSIGNED → ACKNOWLEDGED → IN_PROGRESS. |
| S43d | T | **Add a work note** → Note `Checked the controller: the reading-room access point reboots every few minutes.` → **Add note** | Timeline: Work note · Arjun Menon | Investigation notes. |
| S43e | T | **Request information** → `Which floor and which device?` → **Send request** | **On hold · SLA paused** | The resolution clock pauses while we wait for the user (BR-07). |
| S43f | E | Bell → open INC-2026-0422 → "The technician needs more information from you" → Your message `First floor, my laptop and my phone.` → **Send** | **In progress**; the resolution clock runs again | Employee responds to a support request. |
| S43g | T | Reload → **Suggested fix** | INC-2026-0116 · 63 % similar · "Cleared the stale DHCP leases and the user reconnected." · *Use this fix…* | Suggested resolution from similar past incidents. |
| S43h | T | **Resolve** → What fixed it? `Restarted the first-floor access point.` → **Mark as resolved** | Resolved | Resolution details recorded; the reporter is notified. |
| S43i | E | Reload → **No, it is not fixed** → `It still drops near the windows.` → **Reopen the incident** | In progress · **Reopened ×1** | RESOLVED → IN_PROGRESS: the fix was rejected. |
| S43j | T | Reload → **Resolve** → `Added a second access point by the windows.` → **Mark as resolved** | Resolved | |
| S43k | E | Reload → **Yes, confirm the fix** → **5 out of 5** → **Confirm and rate** | "Fix verified · rated 5/5" | Feedback after resolution (it feeds CSAT on the dashboard). RESOLVED → VERIFIED. |
| S43l | T | Reload → **Close incident** | **Closed · SLA met · Reopened ×1** | VERIFIED → CLOSED; the Timeline shows the whole story. |
| S44 | E | **Report by chat**. Type `Second floor printer is jammed` → Enter. For the second question click **🎤 Answer by voice** and *say* "The printer on the library second floor jams on every page and shows a paper error", then Send. Pick **Printing Service** → **My team or department** → **It works, but badly** → **Yes, Printing** → **Report it** | The bot asks one question at a time; "This looks like a Printing problem · Medium confidence · 67%"; finally "**Done: INC-2026-0427 is reported as P3 and a technician has it.**" | Chatbot and voice reporting (Web Speech API; Chrome or Edge). |

*End of the live take.*

---

## Take 3: engineering evidence and close (16:00–18:00), M4 then all

| # | Screen | Do | You will see | Say |
|---|---|---|---|---|
| S45 | Terminal | Run the four commands below | **409** "An incident cannot move from ASSIGNED to CLOSED." **409** "…from CLOSED to RESOLVED." **422** field errors. **401** "Sign in to continue." | The global handlers map the `ITSMError` hierarchy to HTTP codes; no stack traces leak. NEW → CLOSED-style jumps are impossible. |
| S46 | Tab T (reuse) | Open the repository's latest green **GitHub Actions** run, or show `make test` / `make test-report` output | ~1,140 backend tests (97 % coverage), BR-01…BR-10 named tests, 141 frontend tests, Playwright end to end and accessibility, on SQLite and PostgreSQL | Unit, integration, end-to-end; boundary, invalid input, authorization and business-rule cases. |
| S47 | Closing card | All | Repository link, live Render URL; what next: task queue for the monitor, pgvector similarity, rate limiting |

S45 commands. The API is on 127.0.0.1:8000; run them from any directory. On Windows, use Git
Bash, and write `python` if `python3` is not found:

```bash
TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'content-type: application/json' -d '{"email":"admin@campus.edu","password":"demo1234"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

```bash
curl -s -w '  HTTP %{http_code}\n' -X POST localhost:8000/incidents/INC-2026-0423/close -H "Authorization: Bearer $TOKEN"
```

```bash
curl -s -w '  HTTP %{http_code}\n' -X POST localhost:8000/incidents/INC-2026-0422/resolve -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{"summary":"again"}'
```

```bash
curl -s -w '  HTTP %{http_code}\n' -X POST localhost:8000/incidents -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{"title":"","description":"x","service_id":999,"impact":7,"urgency":3}'
```

```bash
curl -s -w '  HTTP %{http_code}\n' localhost:8000/incidents/INC-2026-0423
```

---

## Coverage: brief → step

| Brief requirement | Shown in |
|---|---|
| Users: Employee, Technician, Administrator, plus Team Lead and IT Manager | S7–S8, S23, S32 |
| Register and log in; invalid login | S19, S6–S7 |
| Incident create / view / update / assign / resolve / close | S10, S15, S14 and S43d, S10 and S16, S43h, S43l |
| Priority from impact × urgency × business criticality, P1–P4 | S10, S25 |
| Two or more assignment strategies, switchable | S16, S40 |
| SLA calculation, deadline tracking, warnings, violation detection and recording | S10, S12, S23, S33 |
| Two or more notification mechanisms | In-app bell and live push (S11, S24, S32), email to the console or SMTP, Telegram (S11) |
| Complete audit history | S17, S34, S42 |
| Five or more search criteria; reports | S41, S42b |
| Persistence | All of it, after `make demo-reset`; S42's hash chain |
| Employee: report, view, track, add info, respond, see resolution, feedback | S10, S43b, S14, S43f, S43l, S43k |
| Technician: view assigned, acknowledge, investigate, notes, status, request info, resolve, workload | S11–S12, S43a, S43c, S43d, S43e, S43h, S43a |
| Admin: users, technicians, services, SLA, categories, strategy, monitor, reports, audit, violations | S38, S37, S39, S35, S40, S15, S42b, S42, S33 |
| Lifecycle and refused transitions (State pattern) | S4, S12, S43c–S43l, S45 |
| Intelligent: duplicate detection | S9, S20, S27 |
| Intelligent: incident correlation | S30, S31 |
| Intelligent: automatic escalation | S23, S32 |
| Intelligent: smart technician recommendation | S16, S40 |
| Intelligent: SLA risk detection | S12, S34 |
| Intelligent: automatic categorisation | S9, S36, S44 |
| Intelligent: suggested resolution | S17, S43g |
| Exceptions: login, unauthorized, invalid transition, duplicate, invalid input | S6, S26, S45, S18, S45 |
| Different GUI per role, links between screens | S8 |
| Innovation: AI classification, resolution recommendation, similarity, root cause, predictive SLA, dependency graph, real-time notifications, voice, chatbot, real-time dashboard, analytics, escalation, cloud deployment | S9, S43g, S20, S30, S34, S31, S11, S44, S44, S31, S42b, S32, S47 |

## If something differs on the day

- **A different assignee in S10:** the configuration differs from the dry runs (most likely a
  Gemini key changing the category). Sign tab T in as whoever the page shows (Admin → Users
  lists each email) and carry on; Workflow 3's names may then differ too.
- **S12 was late and INC-2026-0423 escalated at T+0:30:** say so. It is BR-08 working. The
  later names in Workflow 3 will differ.
- **Notifications but no Telegram:** the link must be made *after* the reset; an unlinked
  recipient is skipped silently.
- **A take goes wrong:** `make demo-reset` and start Take 2 again. Takes 1 and 3 don't depend on it.
