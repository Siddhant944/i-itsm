# I-ITSM — System Architecture, Workflow & Innovation Blueprint (v2)

Oct 24, 2026 · @Siddhant

CS F213 / MAC F212 Object-Oriented Programming · Semester I, 2026–27 · Group \[\_\_\] · Deadline 22 November 2026

## Changes from v1

Version 2 closes v1's MVP gaps, fixes claims the code would not back up, and sets a four-week plan.

- The lifecycle supports hold, reopen, cancel and auto-close: 10 states, 20 legal transitions.
- SLA targets depend on service tier and priority, and the clock pauses while the reporter is asked for information.
- An injectable clock makes SLA tests and the demo deterministic.
- Priority inputs come from plain-language questions; thresholds are documented and overrides are audited.
- A third, smart assignment strategy is added, and workload is weighted by priority.
- Escalation roles now exist in the user model, and escalation uses Chain of Responsibility.
- Categories, services, SLA policies and strategies are configurable as data.
- New intelligent features: hybrid duplicate detection, predictive SLA risk and a service dependency graph.
- New platform features: real-time updates, voice reporting, real email and Telegram alerts, and Google Sign-In.
- Code is organised one package per layer, and the domain imports no frameworks.
- OOP claims are corrected, and the audit trail is append-only and hash-chained.
- The team split is rebalanced, with a demo plan and a traceability matrix.

## 1. Executive Summary

I-ITSM manages the full incident lifecycle, from report to closure, for a campus-scale IT helpdesk. The seed data models campus services: Wi-Fi, LAN, email, LMS, lab PCs, printers and the Fee Payment Portal. The brief's scenario therefore becomes "the fee payment portal is down".

Lifecycle: Report → Classify → Prioritise → Assign → Investigate → Resolve → Verify → Close.

**Stack:** React + TypeScript + Tailwind · FastAPI (Python 3.12) · SQLAlchemy 2 · SQLite in development, PostgreSQL when deployed · Gemini API · Docker · GitHub Actions.

### Assumptions

- One organisation, with tickets in English.
- SLA clocks run 24×7; business-hours calendars are a stretch goal.
- Historical incidents used for analytics and prediction are synthetic seed data.
- Reporters don't set priority; they answer plain-language questions.
- External services (Gemini, email, Telegram) can fail. The system degrades gracefully and never blocks incident creation.

## 2. Architecture

I-ITSM uses five layers, and every dependency points inward to a framework-free domain.

&#91;embedded content: architecture · 5 layers, shared core, external services\]

Requests flow down from the portals to the domain, and persistence implements the domain's repository interfaces from below, so the domain depends on nothing.

### Dependency rule

- `domain/` imports nothing from FastAPI or SQLAlchemy.
- Repository interfaces are defined in the domain.
- SQLAlchemy implementations run in production; in-memory implementations back the unit tests.

### Deployment

- Docker Compose starts the frontend, API and database with one command.
- The deployed version uses a static host, a container host and managed PostgreSQL; free-tier hosts are still to be chosen.
- External services are Gemini, SMTP email, the Telegram Bot API and Google OAuth.
- "Layered" is the logical architecture; containers and the cloud are the physical deployment, not alternatives to it.

### Folder layout

Each member owns folders, recorded in `CODEOWNERS`.

```
backend/app/{core,domain,services,repositories,api}/
backend/tests/{unit,integration}/
frontend/src/{api,components,pages/{employee,technician,admin}}/
e2e/   docs/diagrams/
docker-compose.yml   .github/workflows/ci.yml   AGENTS.md   CODEOWNERS   .env.example
```

## 3. Domain Model

Inheritance is used only for genuine is-a relationships; permissions come from a role-to-permission map, not `isinstance` checks.

&#91;embedded content: user hierarchy · User and five subclasses\]

TeamLead and ITManager carry escalation levels 1 and 3; the Administrator in between is level 2, and the assigned Technician is where escalation starts.

### Relationships

| Relationship | Where |
| --- | --- |
| Composition (lives and dies with the incident) | `Incident` ◆ `SLAClock`, `WorkNote`s, `Resolution`, `Feedback` |
| Aggregation | `Team` ◇ `Technician` |
| Association | `Incident` → reporter, assignee, `Category`, `ITService`, parent incident · `ITService` → `ITService` (`depends_on`) · `AuditRecord` → incident id, never cascade-deleted |

### Configurable as data

Admins change these in the UI, with no code change:

- `Category`: name, required skill, keywords, optional minimum priority.
- `ITService`: criticality 1–3, SLA tier, dependencies.
- `SLAPolicy`: targets per tier and priority.
- The active assignment strategy and its weights.

### Encapsulation conventions

- Attributes are name-mangled (`__attrs`) and exposed through read-only `@property`.
- State changes only through intention-revealing methods, e.g. `incident.acknowledge(actor, clock)`.
- Value objects are frozen dataclasses, and collections are exposed as tuples.
- Full type hints are checked with `mypy --strict`.

## 4. Incident Lifecycle (State Pattern)

The lifecycle has 10 states and 20 legal transitions; the other 80 (from, to) pairs, including NEW → CLOSED, raise `InvalidStateTransitionError`.

&#91;embedded content: incident lifecycle · 10 states, 20 legal transitions\]

The main path accounts for 7 transitions, and hold, reopen and auto-close add 4 more. Reassignment adds 3 (from ASSIGNED, ACKNOWLEDGED and IN\_PROGRESS), and cancelling from the six tinted states adds the last 6.

### Implementation

- `IncidentState`, an abstract base class, defines every trigger. Its default raises the error, and each concrete state overrides only its legal triggers.
- The status is stored as an enum and turned back into a state object through a registry.
- Every transition emits an `IncidentStateChanged` event.
- CANCELLED records a reason: withdrawn, or duplicate of another incident.

### SLA effects

- The first ACKNOWLEDGED meets the response SLA.
- ON\_HOLD pauses the resolution clock, and RESOLVED stops it.
- Reopening resumes the clock; time spent in RESOLVED does not count.

## 5. Core Engines

Five engines turn a report into a prioritised, assigned and monitored incident, and each sits behind an interface so it can be swapped.

### 5.1 Priority

Priority is computed from three plain-language inputs, so reporters cannot inflate it.

- **Impact (I):** "Who is affected?" Just me = 1, my team or department = 2, many people or everyone = 3.
- **Urgency (U):** "Can you keep working?" I have a workaround = 1, it's degraded = 2, I'm blocked = 3.
- **Criticality (C):** taken from the service's configuration.

```latex
S = I \cdot U \cdot C, \qquad I, U, C \in \{1, 2, 3\}
```

| Priority | Score range | Possible scores | Combinations (of 27) |
| --- | --- | --- | --- |
| P1 | S ≥ 18 | 18, 27 | 4 |
| P2 | 9 ≤ S < 18 | 9, 12 | 6 |
| P3 | 4 ≤ S < 9 | 4, 6, 8 | 10 |
| P4 | S < 4 | 1, 2, 3 | 7 |

P1 needs two factors at 3 and the third at least 2; P4 means at least two factors are 1. Because the score is a product, a weak factor pulls priority down. One blocked user on a critical service scores 1 × 3 × 3 = 9 (P2), and a criticality-1 service never computes above P2.

The payment outage scores 3 × 3 × 3 = 27, which is P1.

- A category's minimum priority acts as a floor, e.g. Security incidents are at least P2.
- A technician or admin override requires a reason and is audited.
- `MatrixPriorityStrategy`, an impact × urgency table the admin can edit, is the swappable alternative.

### 5.2 SLA

SLA targets come from the service's tier and the incident's priority. A service's default tier follows its criticality (3 → Gold, 2 → Silver, 1 → Bronze), and the admin can override it.

| Priority | Gold (brief's table) | Silver (×2) | Bronze (×4) |
| --- | --- | --- | --- |
| P1 | 5 min / 30 min | 10 min / 1 h | 20 min / 2 h |
| P2 | 15 min / 2 h | 30 min / 4 h | 1 h / 8 h |
| P3 | 1 h / 8 h | 2 h / 16 h | 4 h / 32 h |
| P4 | 4 h / 24 h | 8 h / 48 h | 16 h / 96 h |

Targets are response / resolution.

- Statuses run ON\_TRACK → AT\_RISK → BREACHED. AT\_RISK comes from the predictive estimate (6.3), falling back to 75 % of the target elapsed (inclusive).
- An incident is breached if and only if now > deadline. Each breach is stored as an `SLAViolation` with its type, time and overrun.
- The monitor is an in-process APScheduler job that runs every 30 s. Warning and breach events fire once per incident.
- A missing policy raises `MissingSLAConfigurationError`; the system applies a global default and alerts the admin.
- The `Clock` interface has three implementations: `SystemClock` in production, `FakeClock` in tests and `AcceleratedClock` (×10) in the demo, which shrinks the P1 response window to 30 s.

### 5.3 Technician assignment

`AssignmentStrategy.select()` keeps only available technicians with spare capacity, then calls the abstract `rank()` (Template Method). If nobody qualifies, it raises `TechnicianUnavailableError`; the incident is queued for the Team Lead and an alert is sent.

Capacity is weighted by priority, costing 4, 3, 2 and 1 points for P1 to P4:

```latex
L_t = \sum_{i \in A_t} c(p_i), \qquad L_t + c(p_{\text{new}}) \le L_{\max} = 10
```

- **`SkillBasedStrategy`** ranks by skill coverage; ties go to the lower load.
- **`LoadBasedStrategy`** ranks by the lowest load.
- **`SmartStrategy`** (the default, and intelligent feature D) ranks by the weighted score below.

```latex
\text{score}(t) = \alpha_1 \sigma_t + \alpha_2 \kappa_t + \alpha_3 x_t + \alpha_4 h_{t,s}, \qquad \alpha = (0.4,\ 0.3,\ 0.15,\ 0.15)
```

```latex
\sigma_t = \frac{|S_t \cap S_r|}{|S_r|}, \qquad \kappa_t = 1 - \frac{L_t}{L_{\max}}, \qquad x_t = \frac{\ell_t}{3}, \qquad h_{t,s} = \frac{n_{t,s}}{\max_j n_{j,s}}
```

The terms are skill coverage, spare capacity, experience level (1–3) and past fixes on service s. The UI shows the top three candidates with reasons, e.g. "2/2 skills · 60 % capacity free · senior · 5 past fixes on this service". The admin switches strategy at runtime; a registry resolves the saved choice, so a new strategy is one class plus one entry.

### 5.4 Notifications

Notifications never block or roll back the change that triggered them.

- Audit records are written in the same database transaction as the change, so the history cannot miss an event.
- Notifications and real-time pushes go out only after the transaction commits.
- Channels implement `NotificationChannel` and are built by `NotificationChannelFactory`: in-app (database plus WebSocket push), email and Telegram.
- Email uses a real SMTP adapter, with a personal Gmail app password or a transactional email service; Telegram uses a Bot API adapter.
- A failed send is logged and retried up to three times.

| Event | Recipients | Channels |
| --- | --- | --- |
| Created | reporter; Team Lead if P1 or P2 | in-app, email |
| Assigned | reporter, assignee | in-app, email; Telegram if P1 or P2 |
| Priority changed | reporter, assignee | in-app, email |
| Info requested / provided | reporter / assignee | in-app, email |
| SLA approaching | assignee, Team Lead | in-app, Telegram |
| SLA violated | assignee, Team Lead, admin | in-app, email, Telegram |
| Escalated | new escalation owner | in-app, Telegram |
| Resolved | reporter, asked to verify | in-app, email |
| Closed | reporter, assignee | in-app |

### 5.5 Escalation

Escalation is a Chain of Responsibility, so levels can change without touching the other handlers.

1. Technician: the assignee.
2. Team Lead: after one missed response target; may reassign.
3. Administrator: after two missed targets.
4. IT Manager: after three missed targets.

An unacknowledged P1 or P2 moves up one level each time its response target elapses again. For a P1, that happens at 5, 10 and 15 minutes.

A resolution breach goes straight to the Team Lead. The SLA monitor triggers the chain, and the chain decides who handles it.

## 6. Intelligent and Innovation Features

Six intelligent features run behind interfaces with deterministic fallbacks, so the demo works even when Gemini is unreachable.

### 6.1 AI classification and suggested resolution

The `AIAdvisor` interface has two implementations:

- **`GeminiAdvisorAdapter`** requests JSON that must match a schema, with a timeout and one retry.
- **`RuleBasedAdvisor`** matches each category's keywords. It is the automatic fallback and the test double, so results are deterministic.

How it is used:

- The Gemini prompt is built from the current category list, so a newly added category works immediately.
- The classifier returns a category, a service and a confidence score. The reporter or technician can override it, and every AI decision is audited.
- Ticket text is passed as clearly delimited data, and output is validated against the schema.
- **Suggested resolution:** the three most similar resolved incidents are retrieved and shown. Gemini summarises them, citing their IDs and nothing else.
- **Voice reporting:** the browser's Web Speech API (Chrome and Edge) turns speech into text for the same intake form.

### 6.2 Duplicates and correlation

Duplicate detection combines text similarity, same affected service and closeness in time, because text overlap alone misses paraphrases. The brief's own INC101–INC103 example scores a Jaccard similarity of 0.20 for every pair, so a 60 % text threshold links none of them.

```latex
\text{sim}(a,b) = \beta_1 \cos(\mathbf{e}_a, \mathbf{e}_b) + \beta_2\, \mathbb{1}[s_a = s_b] + \beta_3\, e^{-|t_a - t_b|/\tau}, \qquad \beta = (0.6,\ 0.25,\ 0.15),\ \tau = 2\ \text{h}
```

- Embeddings come from Gemini, with TF-IDF as the offline fallback, and are stored per incident.
- Two thresholds, θ (suggest a link) and θ-high (reject a repeat), are tuned on about 50 labelled pairs to maximise F1. Precision and recall go in the test report.
- At similarity ≥ θ, the form suggests following the existing ticket while the reporter types, e.g. "INC-0042 Fee portal down: follow this instead?".
- After submission, the technician sees "possible duplicate". Confirming it cancels the new ticket as a duplicate and subscribes its reporter to the parent.
- The same reporter submitting a near-identical ticket (≥ θ-high within 30 minutes) gets `DuplicateIncidentError` (HTTP 409) with a link to the existing ticket.
- **Correlation:** a breadth-first search over `depends_on` flags incidents whose service depends on a service with an open P1 or P2. Example: "likely related to INC-0040 (Database), possible root cause".

### 6.3 Predictive SLA risk

Risk is estimated from how long similar past incidents took, so tickets are flagged on evidence rather than at a fixed 75 %. Take the resolution durations T\_k of past incidents in the same category and priority, excluding paused time. With elapsed time e below the resolution target R\_p:

```latex
\hat{P}(\text{breach}) = \hat{P}(T > R_p \mid T > e) = \frac{\left|\{k : T_k > R_p\}\right|}{\left|\{k : T_k > e\}\right|}
```

- The incident is AT\_RISK when the estimate reaches 0.5.
- If fewer than 10 past incidents lasted longer than e, the 75 % rule applies instead.
- The estimate rises as the ticket ages and reads in plain words, e.g. "x % of past P2 Network incidents still open at 1 h 20 m went on to breach".

### 6.4 Coverage of the brief's lists

| Brief item | Our implementation |
| --- | --- |
| A: duplicate detection; similarity detection | Hybrid score plus duplicate suggestion while typing |
| B: correlation; dependency graph; root-cause analysis | `depends_on` graph plus a live health map (React Flow) |
| C: automatic escalation | Chain of Responsibility |
| D: smart technician recommendation | `SmartStrategy` with reasons |
| E: SLA risk; predictive SLA violation detection | The estimator in 6.3 |
| F: AI-assisted categorisation | Gemini adapter with rule-based fallback |
| G: suggested resolution | Similar resolved incidents plus a grounded summary |
| Real-time notifications and dashboard | WebSockets |
| Voice-based reporting | Web Speech API |
| Cloud deployment, CI/CD, analytics and visualisation | Docker, GitHub Actions, Recharts dashboards |

## 7. Business Rules and Non-functional Targets

Ten business rules govern who may do what and when, and each one maps to at least one automated test.

| ID | Rule |
| --- | --- |
| BR-01 | Employees see and act only on their own incidents. |
| BR-02 | Only the assignee, the escalation owner or an admin may acknowledge, update, request info or resolve. |
| BR-03 | Only the reporter verifies or rejects a fix; unanswered resolutions auto-close after 72 h. |
| BR-04 | Resolving requires a resolution summary. Reopening is allowed only from RESOLVED; a problem after closure becomes a new, linked incident. |
| BR-05 | Priority is computed; overrides need a reason and are audited, and category floors apply. |
| BR-06 | A technician's weighted load stays at or below 10 points, and unavailable technicians are never auto-assigned. |
| BR-07 | The SLA clock pauses in ON\_HOLD, the response SLA is met at first acknowledgement, and breach means now > deadline. |
| BR-08 | Unacknowledged P1 and P2 incidents escalate one level per elapsed response target. |
| BR-09 | Duplicates are handled as described in 6.2. |
| BR-10 | Audit records are append-only, and incidents are never hard-deleted. |

### Non-functional targets

- Search over 10,000 incidents answers within 300 ms at the 95th percentile, measured with Locust.
- Breaches are detected within one 30 s monitor tick.
- The system degrades gracefully when external services fail.
- A new category, service or SLA needs no code; a new strategy or channel needs one class.
- The code passes `mypy --strict`, with at least 80 % test coverage on the domain and services.
- The system starts with one command and runs on SQLite or PostgreSQL.
- Every state change is audited.

## 8. Security and Exceptions

Security is enforced on the server, and every failure maps to one exception class and one HTTP response.

### Security controls

- **Passwords** are hashed with Argon2 or bcrypt.
- **Google Sign-In** is restricted to the campus domain, with the `hd` claim checked on the server. A first Google sign-in creates an Employee account; admins assign other roles.
- **Tokens** are short-lived JWTs.
- **Authorisation** combines role checks with per-incident ownership checks (BR-01) in FastAPI dependencies, never only by hiding buttons.
- **Login protection** locks an account for 15 minutes after 5 failed attempts.
- **Input** is validated by Pydantic, and the ORM parameterises every query.
- **Network:** CORS allows only the frontend's origin, and the deployment uses HTTPS.
- **Secrets** live in an untracked `.env`; `.env.example` is committed, and GitHub push protection is on.
- **Audit** covers logins, failed logins, configuration changes and overrides.

The audit log is hash-chained, and appends are serialised by locking the head of the chain. An admin "verify integrity" action recomputes the chain.

```latex
h_i = \mathrm{SHA256}\left(h_{i-1} \,\|\, \text{record}_i\right)
```

### Exception hierarchy

All exceptions inherit from `ITSMError` through 8 group classes and 14 specific ones. Specific names take the PEP 8 `Error` suffix, e.g. `InvalidStateTransitionError`. Global handlers return consistent JSON and never leak stack traces.

| Group | Specific exceptions | Handling |
| --- | --- | --- |
| `AuthenticationError` | InvalidLogin | 401; counts toward lockout |
| `AuthorizationError` | UnauthorizedOperation | 403; audited |
| `ValidationError` | InvalidUserInput, InvalidIncident | 422 with field errors |
| `NotFoundError` | ServiceNotFound, IncidentNotFound | 404 |
| `ConflictError` | InvalidStateTransition, DuplicateIncident, ConcurrentModification | 409 |
| `AssignmentError` | TechnicianUnavailable, WorkloadExceeded | Automatic: queued for the Team Lead with an alert. Manual: 409 |
| `ConfigurationError` | MissingSLAConfiguration | Default policy plus an admin alert |
| `InfrastructureError` | DatabaseFailure, NetworkFailure | 503 with rollback; external APIs fall back or retry; the frontend shows an offline banner and retries |

## 9. Persistence

Eighteen relational tables hold the system's state, and the same code runs on SQLite in development and PostgreSQL in deployment.

### Tables

- **Identity:** `users` (with a role column), `teams`, `technician_profiles`, `skills`, `technician_skills`.
- **Catalogue:** `categories`, `services`, `service_dependencies`, `sla_policies` (one row per tier and priority).
- **Incidents:** `incidents`, `work_notes`, `resolutions`, `feedback`, `incident_embeddings`, `sla_violations`. SLA clock fields, escalation level and parent id sit on `incidents`, whose `version` column enables optimistic locking.
- **Operations:** `audit_log` (nullable incident id, previous hash, hash), `notifications`, `system_config`.

### Implementation details

- Indexes cover status, priority, assignee, service and created\_at.
- Alembic manages migrations. `seed.py` creates campus services, users and 300–500 historical incidents.
- SQLite connections enable `foreign_keys=ON` (off by default) and WAL mode.
- Timestamps are stored as timezone-aware UTC and shown in IST.
- Text search uses SQLAlchemy `ilike`, which works on both databases.
- CI runs the test suite against both databases.

### Search and reports

- **Filters (9 plus free text):** ID, date range, status, priority, category, service, technician, SLA status, reporter.
- **Dashboards:** overview cards, technician workload and service analysis.
- **Metrics:** mean time to acknowledge and to resolve, SLA compliance %, average satisfaction score and reopen rate.
- **Trends and export:** trends over time, plus CSV export of any filtered list.

## 10. OOP Concepts and Design Patterns

Each required OOP concept and each of the nine patterns maps to named classes that evaluators can open.

### OOP concepts

| Concept | Evidence |
| --- | --- |
| Encapsulation | Name-mangled attributes, read-only properties, changes only through domain methods, frozen value objects, tuple views |
| Abstraction | `IncidentService` facade; `AIAdvisor`, `NotificationChannel`, `Clock` |
| Inheritance | User hierarchy (5 subclasses), 10 state classes, exception hierarchy |
| Polymorphism | `strategy.rank()`, `channel.send()`, `state.resolve()`, `clock.now()` |
| Interfaces | Abstract base classes for strategies, channels, AI advisor, embedding provider, clock and repositories |
| Composition, aggregation, association | See section 3 |
| Exception handling | Grouped hierarchy with HTTP mapping (section 8) |
| Collections | `frozenset` skills (O(1) membership; intersection O(min(len A, len B))), `dict` registries for states, strategies and channels, `deque` plus `set` for graph search, tuples for read-only views |

### Design patterns

| Pattern | Problem it solves | Classes |
| --- | --- | --- |
| State | Rules differ per state, so illegal transitions become impossible | `IncidentState` plus 10 states |
| Strategy | Assignment and priority algorithms swap at runtime | `SkillBasedStrategy`, `LoadBasedStrategy`, `SmartStrategy`; `WeightedProductPriorityStrategy`, `MatrixPriorityStrategy` |
| Observer | Audit, notifications and real-time updates are decoupled from transitions | `EventBus` plus subscribers |
| Factory | Builds role-specific users (including from database rows), channels from config, and incident IDs with defaults | `UserFactory`, `NotificationChannelFactory`, `IncidentFactory` |
| Repository | Isolates persistence; SQLite, PostgreSQL and in-memory stores are interchangeable | `IncidentRepository` and siblings |
| Adapter | Wraps external APIs behind internal interfaces | Gemini, SMTP and Telegram adapters |
| Chain of Responsibility | Escalation levels are configurable | `EscalationHandler` chain |
| Template Method | Shared candidate filtering across assignment strategies | `AssignmentStrategy.select()` calling `rank()` |
| Facade | One entry point for the API layer | `IncidentService` |

## 11. End-to-End Scenario: the Fee Payment Portal Is Down

The brief's 14 steps run automatically once the employee submits a report; each step names the mechanism that performs it.

1. The employee reports by text or voice and sees similar open tickets; `IncidentFactory` creates INC-2026-0042 in NEW (Factory).
2. Gemini suggests the Application category with a confidence score, and the incident moves to CLASSIFIED (Adapter, State).
3. The service is identified as the Fee Payment Portal (Gold, criticality 3), and the dependency graph is checked (Association).
4. Business impact is set: Impact 3, Urgency 3, Criticality 3.
5. The score is 27, so the priority is P1 (Strategy).
6. The Gold P1 SLA applies: respond in 5 minutes, resolve in 30, tracked by a new `SLAClock` (Composition).
7. `SmartStrategy` ranks available technicians and shows the top three with reasons (Strategy, Template Method).
8. The best candidate is assigned, and the incident moves to ASSIGNED (State).
9. The reporter is notified in-app and by email, and the technician on Telegram (Observer, Factory, Adapter).
10. The technician acknowledges, starts work, may put it ON\_HOLD for information, then resolves it with an AI-suggested fix (State).
11. The monitor estimates risk, sends warnings, records breaches and escalates if nobody acknowledges (Chain of Responsibility).
12. Every event becomes a hash-chained audit record (Observer).
13. The reporter verifies and rates the fix, moving the incident to VERIFIED and then CLOSED (State). Rejecting it reopens IN\_PROGRESS, and a NEW → CLOSED attempt is refused.
14. Dashboards update live (Repository, WebSocket).

## 12. Technology Selection

The stack was chosen for a framework-free OOP core, a typed API contract and strong AI libraries; the answers below cover the brief's nine questions.

1. **Programming language: Python 3.12 on the backend, TypeScript on the frontend.**
   - Abstract base classes, dataclasses, enums and type hints express the OOP model concisely.
   - Python has first-class Gemini, embedding and data libraries.
   - It lacks compile-time access control and static typing, so we use name mangling, read-only properties and frozen dataclasses, and enforce `mypy --strict` in CI.
   - TypeScript keeps types consistent end to end, generated from the API contract.
2. **Frontend: React + TypeScript + Tailwind, built with Vite.**
   - Components such as badges, SLA chips and the filter bar are reused across all three portals.
   - The ecosystem provides Recharts, React Flow and installable-PWA support.
3. **Backend: FastAPI.**
   - Pydantic validates every request at the boundary.
   - The OpenAPI spec is generated automatically, giving Swagger docs and our typed client.
   - Dependency injection supplies auth, repositories and the clock, and WebSockets are built in.
4. **Database: SQLite for development and tests, PostgreSQL for deployment.**
   - The data is relational, with integrity constraints between incidents, users, services, policies and audit records.
   - SQLAlchemy 2 and Alembic sit on top, and CI tests both databases.
5. **Architecture: a layered, containerised modular monolith.**
   - Layers separate concerns, and the framework-free domain can be tested in isolation.
   - Package boundaries let four people work in parallel.
6. **Alternatives considered.**
   - Spring Boot + PostgreSQL: compile-time typing, but heavier setup. Python's AI and data libraries also suit our features better on a four-week timeline.
   - Node + MongoDB: rejected, because audit and SLA reporting need relational integrity and joins.
   - Flutter + Firebase: rejected, because technician and admin work needs wide screens, and a responsive PWA covers mobile reporting.
   - Microservices: rejected at this scale; package boundaries allow a later split.
7. **Advantages and limitations.**
   - Advantages: fast development, a typed API contract, automatic docs and a strong AI ecosystem.
   - Runtime typing is a limitation, mitigated by mypy.
   - SQLite allows one writer at a time, so it is used only in development.
   - External AI is a dependency, mitigated by rule-based fallbacks.
   - The in-process scheduler supports a single instance only.
8. **How the stack supports OOP.** Section 10 lists the evidence. Python encapsulation relies on convention, name mangling and immutability, which we verify with static checks rather than claim the language enforces.
9. **Scaling to many more users.**
   - Run stateless API containers behind a load balancer.
   - Use PostgreSQL with indexes and read replicas.
   - Move the SLA monitor and notifications to a task queue (e.g. Redis + Celery) so instances don't duplicate jobs.
   - Use Redis pub/sub to fan out WebSocket messages across instances.
   - Use pgvector for similarity search at scale, plus pagination and cached analytics.

## 13. Testing Strategy

About 200 automated cases, mostly parametrised, cover every business rule and the brief's six test categories.

| Suite | What it covers |
| --- | --- |
| State matrix | All 100 (from, to) pairs: 20 succeed, 80 raise |
| Priority | All 27 combinations, category floors, overrides |
| SLA | The 75 % and deadline boundaries, pause and resume, reopen, missing policy, all on `FakeClock` |
| Assignment | Each strategy, no technician available, capacity cap, runtime switch |
| Similarity | The brief's INC101–INC103; precision, recall and F1 on the labelled set |
| Prediction and escalation | The estimate rises with time and falls back correctly; escalation timings |
| Authorisation | Every role against every endpoint; attempts to open other users' incidents |
| Errors and reliability | Each exception returns its HTTP code; a failed notification doesn't roll back; concurrent edits return 409; a Gemini outage triggers the fallback |
| End-to-end (Playwright) | The three demo workflows |

- Every suite runs in CI with a coverage report.
- At least 15 cases are documented in the brief's categories: normal, boundary, invalid input, exceptions, authorisation and business rules.
- Each documented case has an ID, preconditions, steps, input, expected result, actual result and status.
- Bugs are logged as GitHub Issues linked to the commits that fix them.

## 14. Demo Plan

The 17-minute video shows all three required workflows end to end, and every member introduces themselves and presents their module.

**Setup:** accelerated clock, seeded database, and a split screen with the Employee, Technician and Admin views, plus a phone showing Telegram. Each workflow is one continuous take, captioned with requirement IDs and ending on its audit trail.

- **M1 (4 min):** introduction; class and state diagrams. Workflow 1a: voice report → duplicate suggestion → classification → P1 → SLA.
- **M2 (5 min):** Workflow 1b: smart assignment with reasons → email, Telegram and live in-app alerts. Workflow 3: three payment tickets → duplicates linked → dependency correlation → escalation chain.
- **M3 (4 min):** architecture and ER diagrams, then the admin portal. The admin adds a category live, edits an SLA policy and switches strategy to show a different pick. M3 then runs the 9-filter search, verifies audit integrity and walks through analytics.
- **M4 (4 min):** Workflow 2: acknowledge → request info (clock paused) → reply → AI suggestion → resolve → reject → resolve → verify and rate → closed. An illegal transition is then refused, and CI runs the tests with coverage.

The brief's filename pattern says `2025-2026`, though the semester is 2026–27; the team chose `2026-2027` (D-045).

## 15. Team and Timeline

Work is split by layer so all four members build in parallel, and submission is planned for 21 November, a day before the deadline.

### Ownership

| Member | Code | Report sections | Tests |
| --- | --- | --- | --- |
| M1 Domain and lifecycle | `domain/`, event bus, notification subsystem, admin configuration screens | 1 Problem analysis; 4 UML (use case, class, state, sequence) | Domain, notifications |
| M2 Intelligence and SLA | AI advisor, similarity, dependency graph, predictive SLA, assignment strategies, SLA monitor, escalation, historical seed data | 2 Requirements; 5 Technology stack and the 9 answers | Strategies, similarity precision and recall, escalation |
| M3 Platform | API, auth incl. Google Sign-In, repositories, ORM and migrations, audit, search and analytics plus the dashboard page, Docker, CI and deployment | 3 Architecture; 6 Repository and README; 7 Database and security | Integration, authorisation |
| M4 Frontend and QA | Design system, Employee and Technician portals, real-time client, voice input, health map, PWA | 8 Testing; video editing; final PDF compilation | End-to-end, test report |

### Weekly plan

&#91;embedded content: build timeline · 4 weeks, 7 milestones, recording window\]

The two dry runs close weeks 2 and 3, so anything that slips is caught a week before the freeze.

- **Week 1, foundations:** repo, CI and `AGENTS.md`; API contract; domain and states; ORM and auth; frontend on mock data.
- **Week 2, MVP:** every MVP feature across the three portals; in-app and email notifications; search; audit; seed data.
- **Week 3, intelligence:** AI, duplicates, prediction, escalation, dependency graph, WebSockets, voice, Telegram, Google Sign-In, deployment.
- **Week 4, polish:** bug fixes only after the freeze, then the report and the video.

Report sections are written alongside the code from week 2.

## 16. Traceability Matrix

Every MVP requirement in the brief maps to an implementation, an owner, a test suite and a demo segment.

| Brief requirement | Implementation | Owner | Tests | Demo |
| --- | --- | --- | --- | --- |
| Three user roles | User hierarchy, auth, admin user screens | M1, M3 | T-AUTH | M3 segment |
| Incident create to close | `Incident` and 10 states | M1 | T-STATE | WF1, WF2 |
| Impact, urgency, criticality | Priority strategies | M1 | T-PRIO | WF1 |
| At least 2 assignment strategies | Skill, Load, Smart | M2 | T-ASSIGN | WF1, M3 segment |
| SLA calculation, tracking, violations | `SLAPolicy`, `SLAClock`, monitor | M1, M2 | T-SLA | WF2 |
| At least 2 notification mechanisms | In-app, email, Telegram | M1 | T-NOTIF | WF1 |
| Audit trail | Hash-chained log | M3 | T-AUDIT | All workflows |
| At least 5 search criteria | 9 filters plus free text | M3 | T-SEARCH | M3 segment |
| At least 2 intelligent features | The six features in section 6 | M2 | T-AI, T-DUP | WF3 |
| Persistence | Repositories over SQLite and PostgreSQL | M3 | Integration suite | M3 segment |
| At least 2 design patterns | Nine patterns (section 10) | All | Covered by the suites above | M1 segment |

Demo timestamps are added after recording.
