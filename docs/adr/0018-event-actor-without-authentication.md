# ADR-0018: Every domain event names its actor before authentication exists

- **Status:** Accepted (owner, 2026-11-10: "si, vamos con esa versión")
- **Date:** 2026-11-10
- **Related:** ADR-0001, docs/architecture/data-model.md (`audit`), docs/roadmap/phase-2-backend-and-reconciliation-engine.md (AC-2c.6, 2026-11-10 amendment)
- **Kind:** Technical (audit trail) and security (who an entry blames)

## Context

AC-2c.6 asks that every Phase 2 domain event appears in `audit.events` with its actor. Authentication arrives with the resolution/approvals phase, so Phase 2 has no logged-in user. Events are written to each context's outbox in the transaction of their state change (AS4), and the audit consumer reads them later, so the actor has to travel with the event.

## Decision

- `shared_kernel.Actor` is a value object: a type (`user`, `agent` or `system`) and a non-empty ID.
- Every SQL unit of work is built with the actor of its caller and stamps it on each outbox row it writes (`actor_type`, `actor_id` columns, migration 0004). The audit consumer copies them into `audit.events` unchanged.
- Operator commands and event handlers act as `system`, named after the command or handler (`recon-import`, `recon-reconcile`, `open-case-on-discrepancy-detected`). API endpoints act as `system:api`.
- The only change a person makes in Phase 2, `PATCH /cases/{id}`, requires an `X-Actor-Id` header (missing or empty: `422`) and records a `user` actor with that ID.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Record every event as `system` | The history of a case could not tell the engine from a person once people change cases |
| `X-Actor-Id` on every endpoint | Asks for a claim where nothing in Phase 2 needs it; opening cases, imports and runs are system work |
| Actor inside each event's payload | Every event class would repeat it, and the audit consumer would depend on each payload shape |
| Wait for authentication | AC-2c.6 is a Phase 2 criterion |

## Consequences

- **Positive:** every audit entry names who caused it, and authentication later replaces only where the API takes the actor from; the columns stay.
- **Negative:** `X-Actor-Id` is a claim the client makes and nothing verifies; any caller can name any user until authentication arrives. A manual `POST /cases` is recorded as `system:api`, not as the person.
- **Follow-ups:** take the `PATCH` actor from the authenticated identity (resolution/approvals phase).
