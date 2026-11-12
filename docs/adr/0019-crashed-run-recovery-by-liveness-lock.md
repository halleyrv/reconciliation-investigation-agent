# ADR-0019: A run left running by a crash is recovered through a liveness lock

- **Status:** Accepted (owner, 2026-11-11: "Liveness lock (Recommended)")
- **Date:** 2026-11-11
- **Related:** ADR-0016, ADR-0017, docs/roadmap/phase-2-backend-and-reconciliation-engine.md (2b amendment B7, moved to 2c)
- **Kind:** Technical (concurrency and recovery)

## Context

A reconciliation run is committed as `running` before its output is recorded, so concurrent calls see it and wait their turn (ADR-0016). A process that dies mid-run (crash, killed container, lost host) leaves that row `running` for good, and B7 accepted that it blocks its period, and any period of the ruleset that overlaps it, until something recovers it. The phase asked for "a recovery command or timeout".

## Decision

- The process running a run holds a PostgreSQL session-level advisory lock on the run's ID (`pg_advisory_lock`), on an autocommit connection of its own, from before the `running` row is committed until the run is completed or failed. The connection is then closed, never pooled, so the lock cannot outlive the run.
- Every `ReconcilePeriod` call first takes the ruleset lock and, in a transaction of its own, marks `failed` each `running` run of the ruleset whose lock is free (`pg_try_advisory_xact_lock`): its process is gone, because PostgreSQL drops a session's locks when its connection ends. It then proceeds as before.
- Saving a finished run only changes a row that is still `running`. A process whose run was recovered while it was in fact alive (its connection dropped but it kept working) cannot complete it afterwards; its output transaction rolls back.
- The application sees this through the `RunLiveness` port (`hold`, `is_alive`); it is not part of the unit of work because it spans the run's transactions.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Recovery command (`--recover <run_id>`) | Someone has to notice the blocked period, and nothing stops them from failing a run that is still alive |
| Timeout (`running` longer than N minutes is dead) | N is a guess: too short fails slow healthy runs, too long keeps the period blocked |
| Heartbeat column updated by the run | A periodic writer and still a timeout to tune; the database already knows whether the connection lives |

## Consequences

- **Positive:** recovery is exact and automatic, needs no operator and no tuning, and is safe against a run that is still alive.
- **Negative:** each run holds one extra database connection for its duration. A host that vanishes without closing its TCP connection keeps the lock until PostgreSQL's TCP keepalive notices, so recovery after a lost host is as fast as that setting, not instant.
- **Follow-ups:** none in Phase 2.
