# ADR-0022: The audit trail is an append-only hash chain guarded by a trigger

- **Status:** Accepted (records the design built in P2c T3 and checked by the 2c phase review; confirmed by the owner at the 2c report, 2026-11-15: "si")
- **Date:** 2026-11-15
- **Related:** ADR-0001, ADR-0018, docs/architecture/data-model.md (`audit`, R16, R17), docs/roadmap/phase-2-backend-and-reconciliation-engine.md (AC-2c.6)
- **Kind:** Technical (audit trail) and security (tamper evidence)

## Context

AC-2c.6 asks that every Phase 2 domain event appears in `audit.events` with its actor, that "the hash chain verifies", and that "the application role's `UPDATE` and `DELETE` on `audit.events` are rejected by the database". Events reach the Audit context from each context's outbox through the in-process relay, which may deliver an event more than once and runs from several processes (CLI commands and API requests) at the same time. Phase 2 has a single database role: the one that runs the migrations.

## Decision

- Each entry stores `sha256`, the SHA-256 of the canonical JSON (sorted keys, no whitespace) of its content (source, source event ID, time, actor, aggregate, event type and version, payload) and `prev_sha256`, the previous entry's `sha256`. The first entry has `prev_sha256 NULL`.
- Appends are serialized by a transaction-scoped advisory lock, so the chain is linear; `UNIQUE (prev_sha256)` makes a fork fail in the database.
- An event is audited once: `UNIQUE (source, source_event_id)`, checked under the same lock.
- A `BEFORE UPDATE OR DELETE` trigger rejects every change for every role. `TRUNCATE` is not blocked; test cleanup uses it.
- `VerifyChain` walks the entries in order and reports the first one whose link or hash does not verify.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Append-only by grants alone (`INSERT`/`SELECT` role) | Phase 2 runs as the migration role, which owns the table, so grants reject nothing yet; the separate role stays a deployment follow-up |
| No hash, only the trigger | A change by the table owner (trigger disabled) would leave no trace |
| A hash per entry without the link to the previous one | Detects a changed entry, not a removed or reordered one |
| Signing entries or anchoring the head outside the database | Needs key management or an external store that no phase asked for |
| `SERIALIZABLE` transactions instead of the advisory lock | Every concurrent append would conflict and have to be retried by the relay |

## Consequences

- **Positive:** a changed or reordered entry breaks the chain from that entry on, and the database itself rejects `UPDATE`, `DELETE`, a fork and a duplicate delivery.
- **Negative:** the trail is tamper-evident, not tamper-proof: the table owner can disable the trigger or `TRUNCATE` the table and rebuild a chain that still verifies, and entries cut from its end are not detected. Appends are one at a time across the whole system. No command exposes `VerifyChain` yet; the audit integration tests run it.
- **Follow-ups:** connect the application with its own `INSERT`/`SELECT`-only role (deployment); anchor the chain head outside the database if a later phase needs tamper resistance against the owner.
