# ADR-0020: A period is reconciled only once its bank statements cover it without a gap

- **Status:** Accepted (owner, 2026-11-11: "Batch = statement (Recommended)")
- **Date:** 2026-11-11
- **Related:** ADR-0017 (superseded), ADR-0016, 2b L17 advisory (1), docs/roadmap/phase-2-backend-and-reconciliation-engine.md (2026-11-10 amendment)
- **Kind:** Business (when a period can be closed) and technical (precondition of a run)

## Context

ADR-0017 lets a run start once the imported bank data reaches the due date of the period's last payout, and measures "reaches" as the latest value date of any bank transaction: a high-water mark. A statement imported out of order, or a later statement imported while an earlier one is missing, moves the mark past the due date with a gap in the middle. The run then freezes false `missing_in_bank` findings for the payouts of the gap. The simulator's bank export carries no statement period, only one value date per transaction, and there is no statement entity in Ingestion.

## Decision

The due date rule of ADR-0017 stays: a run starts only when the bank data reaches the period's end plus the settlement lag in business days, otherwise `PeriodNotClosed` and `recon-reconcile` exit 2. What changes is how far the bank data reaches.

- **A bank statement is one imported `bank_transactions` batch.** It covers from the first to the last value date of the transactions it brought.
- **The reach is contiguous.** Statements are taken in order of their first day and merged while each one starts no later than the business day after the reach so far. The first business day inside the period that no statement covers stops the reach: later statements do not count. A gap before the period's start does not.
- The error message keeps its form, `bank data reaches <reach>`, now with the contiguous reach.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Keep the high-water mark (ADR-0017) | A gap between statements closes a period early, the 2b L17 advisory |
| The simulator publishes `statement_from`/`statement_to` and Ingestion stores them on the batch | Exact, but it changes the Phase 1 export contract and touches simulator, ingestion and reconciliation; offered to the owner and not chosen |

## Consequences

- **Positive:** a statement missing in the middle of the bank data keeps the period open, whatever order the statements were imported in. Weekends and bank holidays between two statements are not a gap.
- **Negative:** a statement's coverage is inferred from its transactions. A business day with no movement at the edge between two statements reads as a gap, and the period stays open until a statement that covers that day is imported, possibly never; the operator sees the reach in the message. A missing statement at the very start of the period is not detected, as under ADR-0017.
- **Follow-ups:** an explicit statement period from the bank source would remove both limits.
