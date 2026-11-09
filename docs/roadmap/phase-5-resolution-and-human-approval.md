# PHASE 5 — Resolution and Human Approval

> Drafted by the agent at the owner's request and **approved by the owner on 2026-11-09**. This text is frozen like any other phase file; later changes go to `Amendments`.

Turn an investigated case into a proposed financial action that a human must approve before anything happens, and execute approved actions exactly once. This is where principle 6 ("every consequential action requires explicit human approval") and principle 7 ("retries and idempotency") get a real, testable action to protect.

## Prerequisites

- ADR-0007 (approval policy), ADR-0008 (action execution model) and ADR-0009 (frontend authentication) move to `Accepted` before this phase starts.
- Phase 4 (investigation agent) is reported to the owner.

## Requirements

1. **Proposed actions.** The `ProposedAction` aggregate with three typed action types: `adjustment`, `refund_request`, `write_off` (ADR-0008), stored with class-table inheritance as in `data-model.md`. Amounts in integer minor units (ADR-0002). The approved amount is frozen.
2. **Proposing.** `resolution.api.propose_action(case_id, action, idempotency_key)`. The Phase 4 agent gets a `propose_action` tool that calls it. The agent proposes, it never approves or executes. Every proposal references the case's findings and their evidence IDs, and every amount equals a deterministic calculation from Phase 4.
3. **Approval policy (ADR-0007).** The proposer never approves. Agent-proposed actions always need a human. One approval from an `approver` up to a configurable threshold, two approvals from two different approvers above it. One rejection rejects the action. Every decision carries a reason. The threshold is recorded on the action when it is proposed, and its default value is set in this phase.
4. **Authentication (ADR-0009).** Seeded development users with roles (`viewer`, `analyst`, `approver`) and a signed session. The application layer receives an authenticated `Actor`. The backend refuses to start with development auth outside `local` and `test`.
5. **Human-in-the-loop in the graph.** When the agent proposes an action, the graph interrupts. It resumes when the action is approved or rejected, by reading the decision from PostgreSQL. The LangGraph checkpoint is never the record of an approval.
6. **Execution (ADR-0008).** Executing an approved action writes an `adjustment_entries` row and an outbox event in one transaction. An outbox relay calls the `ActionExecutor` port. Its v1 adapter is a fake gateway that records calls and can be configured to fail or time out. The relay retries with bounded backoff, and effects happen at most once.
7. **Case lifecycle.** `ActionProposed`, `ActionApproved`, `ActionRejected` and `ActionExecuted` move the case through `awaiting_approval → resolved / escalated`. Every event lands in `audit.events` with its actor.
8. **API.** Endpoints to log in, list a case's actions, read one action with its approvals, and approve or reject an action.

## Acceptance criteria

| ID | Criterion |
|----|-----------|
| AC1 | An action cannot be executed without the approvals the policy requires. Proven at the domain level (unit test) and through the API |
| AC2 | The proposer, and the agent for every action it proposes, cannot approve. The same approver cannot approve twice (database `UNIQUE (action_id, decided_by)` and domain check) |
| AC3 | Below or at the threshold, one approval executes the action. Above it, one approval leaves it pending and a second approval from a different approver executes it. One rejection rejects it in both cases |
| AC4 | A user without the `approver` role gets `403` when deciding. An unauthenticated request gets `401` |
| AC5 | Proposing twice with the same idempotency key creates one action |
| AC6 | With the fake gateway configured to fail N times and then succeed, the action executes exactly once: one `adjustment_entries` row and one recorded gateway call that took effect |
| AC7 | The executed amount equals the approved amount. Changing the amount after approval is rejected |
| AC8 | An interrupted graph run resumes after approval or rejection, including after a process restart, and the outcome matches the decision stored in PostgreSQL |
| AC9 | Every action event appears in `audit.events` with its actor, and the hash chain verifies |
| AC10 | The backend refuses to start with development auth when the environment is not `local` or `test` |
| AC11 | `scripts/check.sh` passes, and the full test suite result is reported to the owner |

## Out of scope

| Excluded | Arrives in |
|----------|-----------|
| Approval interface (UI) | Phase 7 (frontend) |
| Real gateway or bank integration | Never: the executor stays a fake (all data is synthetic) |
| OIDC or a real identity provider | Not planned (ADR-0009) |
| Multi-currency actions | Not planned (ADR-0002) |

---

## Amendments

Changes approved by the owner after the original text above. The original is never edited.

| Date | Change | Approved by |
|------|--------|-------------|
