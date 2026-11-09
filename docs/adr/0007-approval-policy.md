# ADR-0007: Approval policy: four-eyes above a threshold

- **Status:** Accepted
- **Date:** 2026-11-09
- **Related:** docs/architecture/bounded-contexts.md (`ProposedAction`, `ApprovalPolicy`)

## Context

Every consequential action requires explicit human approval (principle 6). Financial controls usually scale the required approvals with the amount. The agent proposes actions; it never approves them.

## Decision

- An action is never approved by its proposer. Agent-proposed actions always need a human approver.
- Actions up to a configurable threshold need one approval from a user with the `approver` role.
- Actions above the threshold need two approvals from two different approvers (four-eyes).
- One rejection rejects the action.
- The rule lives in the `ApprovalPolicy` domain service. The threshold is configuration, and it is recorded on each action when the action is proposed.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Single approver always | Simpler, but weakens the control story for large amounts |
| Four-eyes always | Slows down small, low-risk corrections for no real gain |

## Consequences

- **Positive:** A realistic control model, shown clearly in the UI and the audit trail.
- **Negative:** The `ProposedAction` aggregate tracks partial approval. `UNIQUE (action_id, decided_by)` blocks double votes.
- **Follow-ups:** Default threshold value to be set in Phase 5 (resolution and human approval).
