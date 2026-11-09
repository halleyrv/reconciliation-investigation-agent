# Phase Review

Every phase ends with a strict senior-level code review. A phase is not `done` until this review has run, its critical and high findings are fixed, and its report is recorded. The product brief requires a code review in every phase; this document defines how it is done.

## Rules

1. **Independent reviewer.** The review is done by a different agent or session from the one that wrote the code. It receives the phase spec, the ODD document and the diff, not the implementer's conclusions.
2. **No new features.** The review checks what the phase asked for. Scope gaps are reported, not built.
3. **Run the tests.** `scripts/check.sh` and any phase-specific command its acceptance criteria name (for example the evaluation command). Report the observed output, not an expectation.
4. **Fix before done.** Critical and high findings are fixed, each with a test that reproduces it first (TDD bug-fix rule). The re-review checks only those findings, not a new full sweep.
5. **Record it.** The report goes into the phase's ODD document (`odd/tasks/pN-<name>.md`) as evidence, next to the acceptance criteria.
6. **Stop.** The phase result, including this report, goes to the owner. The next phase does not start before that.

## Checklist

| # | Question |
|---|----------|
| 1 | Does the implementation satisfy every requirement and acceptance criterion? |
| 2 | Are there architectural inconsistencies (layer rules, context boundaries, port inventory, ADRs)? |
| 3 | Are there hidden assumptions? |
| 4 | Are edge cases covered? |
| 5 | Are financial calculations correct (integer minor units, single rounding, no `float`)? |
| 6 | Is idempotency actually enforced, by the database and not only by application code? |
| 7 | Are database operations transaction-safe? |
| 8 | Are tests meaningful, or do they only test implementation details? |
| 9 | Are there security issues? |
| 10 | Is the code unnecessarily complex? |

## Severity

| Severity | Meaning |
|----------|---------|
| Critical | Wrong money, data loss or corruption, a broken non-negotiable principle, or a security hole |
| High | A failed acceptance criterion, idempotency or transaction safety not enforced, or a missing test for a business rule |
| Medium | Correct today but fragile: unclear edge case, hidden assumption, misleading test |
| Low | Readability, naming, unnecessary complexity with no behavior risk |

## Report format

- Findings by severity, each with file and line, the concrete failure scenario and the recommended correction.
- Failed acceptance criteria.
- Missing tests.
- Test commands run and their observed results.

## Source

The owner's original instruction, verbatim:

> Perform a strict senior-level code review of the current implementation.
>
> Do not add new features.
>
> Check:
>
> 1. Does the implementation satisfy every requirement?
> 2. Are there architectural inconsistencies?
> 3. Are there hidden assumptions?
> 4. Are edge cases covered?
> 5. Are financial calculations correct?
> 6. Is idempotency actually enforced?
> 7. Are database operations transaction-safe?
> 8. Are tests meaningful or merely testing implementation details?
> 9. Are there security issues?
> 10. Is the code unnecessarily complex?
>
> Run the relevant tests.
>
> Report:
> - Findings by severity.
> - Failed acceptance criteria.
> - Missing tests.
> - Recommended corrections.
>
> Fix critical and high-severity issues before declaring the phase complete.
>
> Do not proceed to the next phase.
