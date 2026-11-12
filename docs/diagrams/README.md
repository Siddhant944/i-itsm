# Diagrams

PlantUML sources with their rendered SVGs. `make diagrams` regenerates the code-derived ones and
renders everything (SVG here, PNG for the report). Java is the only requirement: the sources use
PlantUML's built-in `smetana` layout, so Graphviz is not needed.

| Diagram | Source | Kept true to the code by |
|---|---|---|
| Use case | [usecase.puml](usecase.puml) · [SVG](usecase.svg) | review |
| Architecture (layers and components) | [architecture.puml](architecture.puml) · [SVG](architecture.svg) | import-linter contracts |
| Deployment | [deployment.puml](deployment.puml) · [SVG](deployment.svg) | `docker-compose.yml`, `render.yaml` |
| Sequence, Workflow 1 (report → prioritise → assign → notify) | [sequence-wf1.puml](sequence-wf1.puml) · [SVG](sequence-wf1.svg) | `e2e/tests/wf1.spec.ts` |
| Sequence, Workflow 2 (investigate → SLA → resolve → notify) | [sequence-wf2.puml](sequence-wf2.puml) · [SVG](sequence-wf2.svg) | `e2e/tests/wf2.spec.ts` |
| Sequence, Workflow 3 (duplicates → correlation → escalation) | [sequence-wf3.puml](sequence-wf3.puml) · [SVG](sequence-wf3.svg) | `e2e/tests/wf3.spec.ts` |
| State (incident lifecycle) | [generated/state.puml](generated/state.puml) · [SVG](generated/state.svg) | generated |
| Class: users and permissions | [generated/class-users.puml](generated/class-users.puml) · [SVG](generated/class-users.svg) | generated |
| Class: incident aggregate and states | [generated/class-incident.puml](generated/class-incident.puml) · [SVG](generated/class-incident.svg) | generated |
| Class: the State pattern (ten state classes) | [generated/class-states.puml](generated/class-states.puml) · [SVG](generated/class-states.svg) | generated |
| Class: priority and assignment strategies | [generated/class-strategies.puml](generated/class-strategies.puml) · [SVG](generated/class-strategies.svg) | generated |
| Class: SLA, risk and escalation | [generated/class-sla.puml](generated/class-sla.puml) · [SVG](generated/class-sla.svg) | generated |
| Class: ports and adapters | [generated/class-ports.puml](generated/class-ports.puml) · [SVG](generated/class-ports.svg) | generated |
| ER (database schema) | [generated/er.puml](generated/er.puml) · [SVG](generated/er.svg) | generated |

Everything under `generated/` is written by `backend/scripts/gen_diagrams.py` from the classes
and the SQLAlchemy metadata: members, inheritance and abstractness are read from the code, and
only associations are listed by hand in the script. `tests/unit/scripts/test_diagrams.py` fails
when a committed file no longer matches the code, so run `make diagrams` after such a change.
