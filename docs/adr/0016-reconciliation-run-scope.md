# ADR-0016: A run reports what belongs to its period, anchored on the settlement batch date

- **Status:** Accepted (owner, 2026-11-10: "Por fecha de batch")
- **Date:** 2026-11-10
- **Related:** ADR-0011, ADR-0014, docs/roadmap/phase-2-backend-and-reconciliation-engine.md (AC-2b.5, API surface "Run the engine for a period"), docs/architecture/data-model.md (`recon`), odd/tasks/p2b-reconciliation-engine.md (phase review H1, H2)
- **Kind:** Business (which period a discrepancy belongs to) and technical (constraints)

## Context

A `ReconciliationRun` is idempotent by `(period, ruleset_version)`, but the first implementation used the period only as a name: every run reconciled every ingested record. The phase review reproduced it on the seed-42 sample: a 2030 period and a 1-15 October period each completed with the same 41 discrepancies as the whole month, 123 rows for 41 root causes. In 2c the `DiscrepancyDetected` handler opens one case per discrepancy, so overlapping runs would open duplicate cases.

The same review found that a completed run stays final even when it ran without reference data (no fee schedule, no holiday calendar), and that a corrected rerun under a new ruleset version failed, because the fingerprint was unique across all runs.

Records reference each other across days. A refund is absorbed by a later batch than its payment's, and a payout names a batch dated two business days earlier. So filtering the input by date would make cross-period references look dangling.

## Decision

Rules always run over every ingested record, so every reference resolves. The run keeps only what belongs to its period:

- Every record has an **anchor date**: the batch date of the settlement batch it settles in. A record whose batch reference resolves to nothing falls back to its own date (capture, refund or value date). An order follows its earliest payment, or its placed date when nobody paid it. A fee follows its payment, and a refund authorization follows its refund.
- A **discrepancy** belongs to the period holding the latest anchor date among its records: an anomaly is reported once its last record has settled. A **match group** belongs to the period of its settlement batch.
- Live runs (`running` or `completed`) of one ruleset never share a day: `EXCLUDE USING gist (ruleset_version WITH =, period WITH &&) WHERE (status <> 'failed')`. Adjacent periods are allowed, and a failed run does not block its period.
- A run fails, and records why, when a fee of its period has no applicable fee schedule, or when a year of its period has no loaded holiday calendar (`recon.calendar_years`). It never reports unchecked money as clean (principle 10).
- `fingerprint` is unique per run (`UNIQUE (run_id, fingerprint)`). Idempotency comes from the one-live-run rule. A new ruleset version can reconcile a period again, for example after reference data was corrected.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Filter the input records by date before the rules run | Cross-period references (a refund absorbed by a later batch, a payout two business days later) would look dangling and produce false `reference_mismatch` discrepancies |
| One period per database: the period must cover every ingested date | A stopgap. Reconciling a second month would be impossible until real scoping existed |
| Anchor on the earliest record instead of the latest | An anomaly whose last record arrives later (an unauthorized refund absorbed the next month) would be reported in a period already closed |
| Keep the fingerprint globally unique and add the ruleset version to it | Same effect as a per-run key, but every consumer would have to know that the ruleset is part of a discrepancy's identity |

## Consequences

- **Positive:** adjacent periods split the whole-data result exactly (tested on a unit book and on the seed-42 month split in halves). Re-running a period is idempotent, an overlapping period is refused, and missing reference data is visible instead of silent.
- **Negative:** every run reads every ingested record. That is fine at the current volumes, and a run's own SQL can later narrow it to the anchor window. A fee whose payment and batch references both dangle has no anchor date and joins no period. That gap is marked as a shortcut in the code.
- **Follow-ups:** `DiscrepancySuperseded`, so that a rerun under a new ruleset retires the earlier run's discrepancies. A command to fail a run left `running` by a crash (B7).
