# Demo script

The recorded presentation (requirements §9 and the Important Note): 15–20 minutes, all four
members on camera, each introducing themselves and explaining a module, and **three complete
workflows**. Planned length: **17 minutes**. Based on blueprint §14, updated for what was built
(voice input, the health map and chat reporting are back, D-039; light and dark themes, D-040).

**File name:** `15_OOP_S1_2025-2026_Project` — the brief's example uses 2025-2026 although the
semester is 2026–27. **Confirm the year with the IC before uploading** (still open).

## Before recording

On Windows without `make`, every `make <target>` below is `uv run scripts/dev.py <target>`
(e.g. `uv run scripts/dev.py demo-reset`).

0. **On the recording machine, once:** pull `main`, then `make setup` (or `npm ci` in
   `frontend/` and `e2e/`: the health map and the accessibility test added packages). If
   `.env.local` exists (written by `neon init`), delete it or set
   `DATABASE_URL=sqlite:///./itsm.db`: it points at the production database, and
   `make demo-reset` refuses to wipe that. Allow the browser's microphone for voice input
   (Chrome or Edge).
1. **Rehearse.** Start `make demo-reset`, and in a second terminal run
   `cd e2e && npx playwright test -c demo` (about 2 minutes). It walks every workflow shot below
   on the real ×10 clock and prints when Workflow 3's escalations fire (last run: 33, 63 and
   94 s after the report). It changes the data, so **`make demo-reset` again** before the take.
2. `make setup` once, then **`make demo-reset`** right before each take. It wipes and reseeds the
   local database, settles the history's old P1/P2 outages so the health map starts **all
   green** (D-041), stages two incidents and serves the API and web app on the **×10 clock**
   (one real minute = ten clock minutes; a P1's 5-minute response target passes in 30 seconds).
   It prints the IDs of the staged incidents; note them.
   - Workflow 1's look-alike: *"Fee payment portal page is very slow"* (Fee Payment Portal),
     reported by another employee, so the live report shows the duplicate hint.
   - Workflow 2's ticket: *"Wi-Fi keeps dropping in the library reading room"*, reported by
     Devika Rao and already in Arjun Menon's queue.
3. Three browser windows side by side, each its own sign-in (a tab keeps its own session):
   - Employee portal — `employee@campus.edu` (Devika Rao)
   - Technician portal — `technician@campus.edu` (Arjun Menon)
   - Admin portal — `admin@campus.edu` (Rahul Verma)

   Keep `lead@campus.edu` (Priya Nair, Team Lead) and `manager@campus.edu` (Sunita Iyer) ready
   in a fourth window for Workflow 3. All passwords: `demo1234`.
4. Optional: Telegram alerts on a phone in shot. `TELEGRAM_BOT_TOKEN` in `.env`; the phone's
   owner has pressed **Start** in the bot's chat and read their chat ID from @userinfobot.
   - **Link after the final `make demo-reset`**: the reset wipes the database, links included.
     One chat ID may be linked to several accounts (header → Telegram alerts → save).
   - **Which accounts.** Escalation goes to the lead *of the assignee's team*, then the first
     Administrator, then the IT Manager (§5.5); the Smart strategy decides the team, so it is
     often not Priya's. Link `admin@`, `manager@` and every team lead: `lead@`, `s.desk1@`,
     `sys1@`, `id1@`, `sec1@`. Add `technician@` for Workflow 2's alerts. An unlinked
     recipient is skipped silently (its row still reads `sent`).
   - If the P1 is assigned straight to a team lead, level 1 is skipped (it already holds it)
     and only two escalation alerts arrive. That is correct; say so.
   - A few minutes after the reset, *SLA approaching/breached* alerts arrive for the staged
     Fee Payment Portal ticket (any priority breach alerts the admins). Expected.
   - Close Telegram on the recording laptop: while it is active there, Telegram may not push
     to the phone. Phone: Do Not Disturb off, the bot's chat not muted.

   Email shows in the API console when SMTP is not configured. Without a Gemini key the
   suggestions say "from keyword rules" — that is the fallback working, say so.
5. Open `report/build/main.pdf` (`make report`) at the class and state diagrams, and
   `docs/diagrams/architecture.svg` and `generated/er.svg`.
6. Screen at 1280×800 or larger, browser zoom 100 %, the laptop's notifications off (the
   phone's stay on for Telegram). Record each workflow as
   one continuous take; caption the requirement IDs in editing.

Every workflow ends on the incident's audit trail (Admin → Incidents → the incident → Timeline,
or Admin → Audit log filtered by the incident).

## Shot list

| # | Time | Who | What is on screen | What to say / do |
|---|---|---|---|---|
| 1 | 0:00–1:00 | All | Title card, then each face | Each member: name, ID, module (M1 domain and lifecycle, M2 intelligence and SLA, M3 platform, M4 frontend and QA). |
| 2 | 1:00–2:30 | M1 Tushar | Report PDF: use case and class diagrams | Problem and the three user groups; the domain model: `User` hierarchy (permissions as data, not `isinstance`), the `Incident` aggregate and what it owns. Point out that the class and state diagrams are generated from the code. |
| 3 | 2:30–3:30 | M1 | State diagram, then `backend/app/domain/states.py` | Ten states, exactly 20 transitions; the base class refuses every trigger and each state overrides only what it allows. |
| 4 | 3:30–5:00 | M1 | **Workflow 1a** — Employee portal → Report an incident | Type *"Fee payment page fails at checkout"*, then click **Describe it by voice** and *say* the description (Chrome or Edge; the words appear as you speak), service **Fee Payment Portal**. Show the **suggested category with its confidence** ("Use this suggestion" — nothing applied silently) and the **"This may already be reported"** card with the staged incident and its match reasons. Carry on (it's a different problem). Answer *Many people or everyone* / *I am blocked*. Submit. |
| 5 | 5:00–6:30 | M2 Siddhant | **Workflow 1b** — the new incident's page | Priority from impact × urgency × business criticality (Gold service, criticality 3 → P1), the SLA deadlines starting to count down, the assignee chosen by the **Smart strategy** — say who it picked and why; it depends on skills and live workloads, so it need not be Arjun. In the admin window open the incident → assignment advice: top three candidates **with reasons**. Then sign the technician window in as **the assignee shown** (Admin → Users lists each email; password `demo1234`): the bell shows the new assignment and the incident is in their queue, pushed live over the WebSocket. Mention email/Telegram for P1/P2. This P1 escalates too (about 30, 60 and 90 s after it is reported) unless its assignee clicks **Acknowledge**: do that at the end of the shot, or point at the *Escalated* badge as a preview of BR-08. |
| 6 | 6:30–9:00 | M2 | **Workflow 3** — several reports, duplicates, correlation, escalation | (a) As Devika, report a payment problem on the **Fee Payment Portal**; as another employee start a similar one — the form suggests it; click **Follow this instead**. (b) The technician holding a payment ticket → **Possible duplicates** → confirm. (c) **Now** report the P1 in a fourth window as another employee: *"Database cluster not responding"*, service **Database Cluster**, many people / blocked — the escalation clock starts here, so (d) and (e) follow straight away. (d) Open the fee-portal incident → **Related through services**: *likely related to* the database P1, *possible root cause*. Then Admin → **Service health**: the Database Cluster is red (outage) with red, moving arrows to everything built on it, and in the table the Fee Payment Portal's *Trouble comes from* column names the Database Cluster. (demo-reset settled the old outages, so the map opened all green; the Fee Payment Portal is red from this take's own P1s, and now the Database Cluster turns red with everything built on it.) (e) Nobody acknowledges the database P1: ~30 s after (c) it breaches and **escalates to the Team Lead**, ~60 s to an **Administrator**, ~90 s to the **IT Manager** (BR-08). Show Admin → **SLA violations** and the incident's escalation level. |
| 7 | 9:00–10:00 | M3 Shri Krishna | Architecture diagram, ER diagram | Five layers, dependencies inward, enforced by import-linter in CI; the facade; audit written in the same transaction, notifications after commit. 18 tables, SQLite and PostgreSQL, both tested in CI. |
| 8 | 10:00–12:30 | M3 | Admin portal | **Categories**: add *"Printer"* live and show it in the report form at once. **SLA policies**: edit one target. **Assignment**: switch Smart → Load-based and show a different pick in the advice. **Incidents**: combine filters (status + priority + service + date), export CSV. **Audit log**: **Verify integrity** → intact (the chain is hash-linked). **Dashboard**: MTTA, MTTR, SLA compliance, CSAT, trends. |
| 9 | 12:30–15:30 | M4 Ishaan | **Workflow 2** — Technician portal, the staged Wi-Fi ticket | Optional opener: in **My queue** click the **SLA** header (the next deadline comes first) and flip the console to **Light** and back with the theme switch in the header (D-040). **Acknowledge** → **Start work** (only the next legal step is offered). **Request information** ("Which floor and which device?") — the SLA chip shows *paused*. Employee window: the question arrives; **reply** → back to In progress, clock resumes. Technician: open **Suggested fix** (similar past incidents), **Resolve** with a summary. Employee: **Reject** with a reason → reopened. Technician resolves again. Employee: **Verify** and rate 5 ★. Technician: **Close**. Show the timeline and the notifications on both sides. Then, briefly, Employee → **Report by chat**: answer the questions (one by voice), see the look-alike and the AI category offered, and file it. |
| 10 | 15:30–16:15 | M4 | Swagger (`/docs`) or a terminal | Try an illegal transition (e.g. resolve a closed incident) → **409 invalid_state_transition**, no stack trace. Another employee opening Devika's incident → **403**. |
| 11 | 16:15–16:45 | M4 | Terminal or GitHub Actions | `make test` (or the CI run): ~1,100 backend tests, 97 % coverage, BR-01…BR-10 named tests; the Playwright workflows; the generated test report. |
| 12 | 16:45–17:00 | All | Closing card | Repository link, what we would do next (task queue for the monitor, pgvector, rate limiting). |

### Timing at ×10

| Clock time | Real time | Gold P1 that nobody acknowledges |
|---|---|---|
| 3 min 45 s | ~22 s | at risk (75 % of the 5-minute response target) |
| just after 5 min | ~30 s | response breached → Team Lead (level 1) |
| just after 10 min | ~60 s | Administrator (level 2) |
| just after 15 min | ~90 s | IT Manager (level 3) |

If a take runs long, the staged Wi-Fi ticket (P4) is not at risk for hours of clock time, so
Workflow 2 can be recorded last without a reset. Workflow 3's P1 must be reported live, and
only once the duplicate steps are done: its escalations all happen within about 90 real
seconds of reporting it.

## Checklist

- [ ] File-name year confirmed with the IC
- [ ] Recording machine on the latest `main`, `.env.local` gone, microphone allowed
- [ ] Rehearsal passes (`cd e2e && npx playwright test -c demo`), then a fresh `make demo-reset`
- [ ] `report/build/main.pdf` built (`make report`) for shot 2
- [ ] `make demo-reset` immediately before each take
- [ ] If showing Telegram: the accounts in item 4 linked *after* that reset; "Send a test"
      reaches the phone
- [ ] Each member introduced and explained a module
- [ ] Workflows 1, 2 and 3 each shown end to end, each ending on its audit trail
- [ ] Captions with requirement IDs added in editing
- [ ] Video length 15–20 minutes; uploaded by **21 Nov** (hard deadline 22 Nov)
