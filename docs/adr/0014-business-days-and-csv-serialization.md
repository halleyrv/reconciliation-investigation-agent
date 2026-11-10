# ADR-0014: Business-day calendar for settlement, and the CSV serialization contract

- **Status:** Proposed
- **Date:** 2026-11-09
- **Related:** ADR-0002, ADR-0013, docs/roadmap/phase-1-financial-data-simulator.md (AS6, interface, 2026-11-09 amendments), docs/roadmap/phase-2-backend-and-reconciliation-engine.md (AS3)
- **Kind:** Business (which calendar the bank observes) and technical (configuration and CSV dialect)

## Context

AS6 says batches are "paid T+2 business days", but the spec never defines a business day. Phase 2 AS3 assumes "Monday to Friday, no holidays, matching the simulator's T+2 rule (Phase 1 AS6). To be confirmed against the simulator implementation".

The owner has already approved, in the Phase 1 amendment of 2026-11-09, that "monetary values are `Decimal` inside the simulator and are exported as decimal strings (for example `"123.45"`), never as JSON floats". **That decision is not reopened here.** The CSV dialect, however, is not specified anywhere.

### Evidence status

| Aspect | Status |
|--------|--------|
| T+2 business days | **Spec** (AS6) |
| Money as decimal strings, never JSON floats | **Spec, approved** (amendment 2026-11-09). Referenced, not restated as a new decision |
| Business days = Monday to Friday, no holidays, not configurable | **Implemented** in `sim.py:add_business_days`, used by the generator and by the checker. **Hypothesis**: not approved |
| Weekend handling | **Tested**: `test_settlement_lag_skips_weekends` (Friday → Tuesday, Saturday → Tuesday) |
| Dates and timestamps as ISO strings (`2026-10-07`, `2026-10-03T14:22:05Z`) | **Implemented**. JSON has no date type, so this follows from the format, not from a choice |
| Every field in CSV and JSON is a string; CSV and JSON hold identical values | **Implemented and tested** (`test_monetary_values_are_exported_as_decimal_strings`, `test_validate_files_detects_csv_that_differs_from_json`) |
| CSV dialect (encoding, delimiter, quoting, line ending, header) | **Implemented** in `export.py:to_csv` (Python `csv` defaults), **not specified or tested** beyond "CSV equals JSON" |

## Decision (proposed)

### Part 1: business days (pending, business decision)

Make the holiday calendar part of the config: `holidays: ["YYYY-MM-DD", ...]`, empty by default, so the current Monday-to-Friday behavior stays the default. The settlement policy document lists the holidays, and I9 checks that list against the config, as it already does for the fee schedule and the lag.

Which calendar to use (none, a US federal list, a fictional one) is the owner's business decision.

### Part 2: CSV serialization (technical)

The CSV contract, as implemented today, written down so ingestion can rely on it:

| Rule | Value |
|------|-------|
| Encoding | UTF-8, no byte-order mark |
| Delimiter | comma |
| Line ending | `\n` (LF), including after the last row |
| Header | one row, column names in the order of the record schema's properties |
| Quoting | only when a value contains a comma, a quote or a line break; quotes are doubled (RFC 4180 style) |
| Values | every value is the same string as in the JSON file; money, dates and timestamps follow the approved amendment |
| Empty values | none; every column is required |

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Keep Monday to Friday with no holidays as a fixed rule | Simple and what Phase 2 AS3 assumes, but delayed settlement around a holiday would be indistinguishable from a legitimately late one |
| A hardcoded real-country holiday list | Ties synthetic data to a jurisdiction the project does not model (AS3, one merchant, fictional gateways) |
| Typed JSON (numbers for amounts) with strings only in CSV | Contradicts the approved amendment. Not an option |
| A CSV dialect with `;` delimiter or CRLF | No consumer needs it; LF and comma are what Python and PostgreSQL `COPY` read by default |

## Impact on the data model

- Config gains `holidays` (Part 1). The manifest's resolved config includes it.
- No record field changes.

## Impact on validations

- Part 1: the generator and the checker use the same calendar from the config; I9 also compares the holiday list in `settlement_policy.md`. Phase 2's settlement-lag rule must read the same calendar, so Phase 2 AS3 is affected.
- Part 2: `validate_files` should also check the dialect (no BOM, LF endings, header order), which today it checks only partly (header order and values).

## Tests needed

- Part 1: a batch before a configured holiday pays one business day later; a run with holidays verifies (AC2/AC3); I9 detects a holiday list that differs from the config.
- Part 2: a test that the CSV has no BOM, uses LF and quotes a value containing a comma (no current record has one, so it needs a crafted row).

## Dependencies

- ADR-0013: the delayed-settlement row uses this calendar.
- Phase 2 AS3 must be updated by the owner if Part 1 is accepted.

## Consequences

- **Positive:** settlement dates can be realistic; ingestion has a written CSV contract.
- **Negative:** the calendar must be shared by the simulator, its checker and the Phase 2 engine.
- **Follow-ups:** the owner chooses the calendar; Phase 2 AS3 amendment.
