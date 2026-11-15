# ADR-0021: A completed run is replaced only on request, and its cases follow their discrepancies

- **Status:** Accepted (owner, 2026-11-12: "Explicit flag (Recommended)"; case rule D3, 2026-11-11: "Trasladar por huella (Recomendado)")
- **Date:** 2026-11-12
- **Related:** ADR-0016, ADR-0019, ADR-0001, docs/roadmap/phase-2-backend-and-reconciliation-engine.md (2026-11-10 and 2026-11-11 amendments)
- **Kind:** Business (when a period's findings are replaced, what happens to its cases) and technical (run states, constraints, event delivery)

## Context

A completed run is final: reconciling its period and ruleset again returns it and writes nothing (AC-2b.5). Data imported after it, or a corrected source, never reaches its findings. Replacing it must decide what triggers the replacement, how the replacing run coexists with the run it replaces under the rule that live runs of a ruleset never share a day, and what happens to the cases already opened on its discrepancies (D3: a case found again moves, keeping status, assignee, version and history; the others close as `resolved`, reason `superseded`). Events are delivered in-process at least once, and a failing handler does not stop the next rows (ADR-0001), so the two contexts cannot rely on event order.

## Decision

- **Explicit trigger.** `recon-reconcile --replace` and `POST /reconciliation-runs` with `"replace": true`. Without it nothing changes. With it and no completed run of the period, it is an ordinary run; a run in progress is `RunInProgress`; an overlapping period is still `PeriodOverlaps`.
- **The replacing run runs next to the run it replaces.** Migration 0005 splits the exclusion constraint: two `running` runs of a ruleset never share a day, nor two `completed` ones. The run start keeps the ruleset lock, so an ordinary run still never starts beside a completed one. `find_live` returns a running run before a completed one, so every caller sees the replacement in progress.
- **One transaction swaps them.** The transaction that writes the replacing run's output also sets each discrepancy of the old run to `superseded`, with `superseded_by` naming the new discrepancy of the same fingerprint or `NULL`, emits one `DiscrepancySuperseded` for each, sets the old run to `superseded` (its finish time stays) and completes the new one. A replacement that fails leaves the old run and its discrepancies untouched.
- **Cases converge in any event order.** `OpenCase` refuses a superseded discrepancy (`DiscrepancyRetired`, `409` on `POST /cases`) and, for a discrepancy with predecessors, moves the case of the nearest predecessor that has one (`CaseCarriedOver`, one guarded `UPDATE` on the case's current discrepancy). `DiscrepancyDetected` of the new discrepancy and `DiscrepancySuperseded` with a successor both call it, so whichever arrives first moves the case and the other finds it moved. `DiscrepancySuperseded` without a successor resolves the case with `close_reason = 'superseded'`, one version later (`CaseResolved`); a case already closed stays as it is.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Replace automatically when an import completed after the run started | A plain call could close cases nobody asked to close; offered to the owner and not chosen |
| Mark the old run `superseded` when the replacing run starts | A replacement that fails or crashes leaves the period with no completed run and needs undoing |
| A `replaces_run_id` column and a predicate that exempts the replacing run | Same coexistence with a more complex predicate and a second column to keep right |
| Move cases in the `DiscrepancySuperseded` handler only | A failed delivery of it lets `DiscrepancyDetected` open a second case for the same finding |
| Close every old case and open new ones | Loses status, assignee and history; D3 chose the carry-over |

## Consequences

- **Positive:** a period's findings can be refreshed without losing the work on its cases. The database still guarantees one completed run per day and ruleset, and the swap is all or nothing.
- **Negative:** the constraint no longer stops an ordinary run from starting beside a completed one; the ruleset lock and `find_live` do, and the completed run's constraint still stops it from completing. A carry-over through `POST /cases` (a client opening the case before the events are delivered) is answered `200` and its `CaseCarriedOver` is delivered by the next command.
- **Follow-ups:** retiring a run under a new ruleset version (ADR-0016) is still not built.
