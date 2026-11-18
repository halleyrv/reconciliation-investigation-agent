# ADR-0017: A period is reconciled only once its last payouts are in the bank data

- **Status:** Superseded by ADR-0020 (accepted by the owner, 2026-11-10: "dale, agregá el corte ahora en 2b y el reemplazo de runs en 2c")
- **Date:** 2026-11-10
- **Related:** ADR-0014, ADR-0016, docs/roadmap/phase-2-backend-and-reconciliation-engine.md (2026-11-10 amendment)
- **Kind:** Business (when a period can be closed) and technical (precondition of a run)

## Context

Under ADR-0016 a completed run is final for its period and ruleset, and a record belongs to the period of its settlement batch. Payouts arrive T+2 business days after their batch, so the last batches of a period are paid in the next one. Reconciling October on November 1 would therefore report the batches of October 29-30 as `missing_in_bank`. The run would be frozen with those false findings, and a payout imported later would belong to October and be reconciled by no `v1` run. In 2c, the `DiscrepancyDetected` handler would open a case for each false finding.

## Decision

A run starts only when the imported bank data reaches the due date of the period's last payout: the period's end plus the settlement lag in business days. "Reaches" means the latest value date of any imported bank transaction. Otherwise `ReconcilePeriod` raises `PeriodNotClosed` before any run is recorded, and `recon-reconcile` exits 2 with both dates. The holiday-calendar check computes the same due date, so it asks for the next year's calendar only when that due date falls in the next year.

Replacing a completed run, with its own transaction and `DiscrepancySuperseded`, moves to 2c, because what happens to the cases of replaced discrepancies is the 2c case model.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Only document an operating rule (run a period after T+2) | Nothing enforces it; one early run freezes wrong findings |
| Allow re-running a completed period now (supersede in 2b) | It needs the case lifecycle of 2c to decide what happens to cases already opened |
| Wait a fixed number of days after the period | Not tied to the data: a late statement still freezes false findings, and a punctual one waits for nothing |

## Consequences

- **Positive:** a run never reports a payout as missing only because its statement was not imported yet.
- **Negative:** the latest value date is a proxy for statement coverage. A statement that holds no transaction on its last days does not move it, so the operator may have to wait for the next movement. A genuinely missing payout is reported only once later bank data exists.
- **Follow-ups:** run replacement and `DiscrepancySuperseded` (2c). An explicit statement-coverage date, if the bank source ever publishes one.
