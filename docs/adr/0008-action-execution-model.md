# ADR-0008: Action execution through an adjustment ledger and outbox

- **Status:** Accepted
- **Date:** 2026-11-09
- **Related:** ADR-0007, docs/architecture/data-model.md (`resolution`)

## Context

Approved actions must have a real, observable effect so that the human-in-the-loop flow is meaningful. There is no real gateway or bank. Execution must be idempotent and survive retries, including LangGraph re-running a node when it resumes.

## Decision

- Executing an approved action writes an `adjustment_entries` row and an outbox event in one transaction.
- An outbox relay calls the `ActionExecutor` port. Its v1 adapter is a fake gateway that records calls and can be configured to fail.
- `proposed_actions.idempotency_key` and `adjustment_entries.action_id UNIQUE` guarantee at-most-once effects.
- v1 action types: `adjustment`, `refund_request`, `write_off`.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Only change the action status | No observable effect. The retry and idempotency story stays untested |
| Call the external executor inside the approval transaction | A failed call leaves the database and the external system out of sync |

## Consequences

- **Positive:** Shows the outbox pattern, idempotent retries and failure handling in a realistic way.
- **Negative:** An outbox relay process and its tests.
- **Follow-ups:** Read models reflect executed adjustments in the reconciliation summary.
