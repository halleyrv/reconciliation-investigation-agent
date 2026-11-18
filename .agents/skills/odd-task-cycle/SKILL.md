---
name: odd-task-cycle
description: "Trigger: continue with TX, continua con TX, start the task, close the task, close the phase. Run one ODD task or the phase closure of this repo."
license: Apache-2.0
metadata:
  author: "halleyrv"
  version: "1.0"
---

## Activation Contract

Load when the owner starts, resumes or closes a task of the active phase (`odd/tasks/pN-<name>.md`), or closes the phase.

## Hard Rules

- Rules live in `AGENTS.md`; this skill orders them and adds known traps. Never restate or override them.
- Cut the task branch `feat/pN-tX-<name>` from the updated phase branch, never from another task branch.
- Never build on a red `scripts/check.sh`: fix the baseline first, in its own commit.
- Every rule gets a RED test run before the code; record the exact command and its relevant output for RED and GREEN.
- Assert the business effect (persisted state, response, output), not the mechanism.
- Commands that write tracked files (`recon-evaluate --report`) and any data-mutating probe run against a scratch path or a scratch database you create and drop.
- Review the task's slice, never the accumulated phase branch.

## Decision Gates

| Situation | Action |
|-----------|--------|
| Gentle AI available | Assess the slice: `gentle-ai review assess --cwd . --agent <agent> --base-ref <task start> --committed-only --json`; add `--escalate-item N --escalate-reason "..."` for a high-risk item; follow its `next_transition` |
| Gentle AI unavailable | Skip native review; say so in the ODD log |
| Stop hook offers the whole phase range | Do not start it; assess the slice and log why in the ODD document |
| `review_due` false (`passive`, `under_budget`) | Log the reason; no review |

## Execution Steps

1. **Start:** branch; run `scripts/check.sh`; append an ODD log entry with the owner's words verbatim and the baseline result (exit code, count, duration).
2. **Build:** per rule, RED -> GREEN -> refactor; log both runs in the ODD entry of the task.
3. **Close the task:** run `scripts/check.sh`; commit in reviewable slices (body on every type except `docs`, `style`, `chore`; no AI attribution); run the native review gate above; update the task row (status, evidence, commits) and the log.
4. **Close the phase:** run `docs/process/phase-review.md` with an independent reviewer; fix critical and high findings with a test first; re-check only those findings; verify AC-level docs (README commands actually run, `data-model.md` against migrations, ADR index); record the report in the ODD document; report to the owner and stop.

## Known Traps

- `ruff format` also formats Python code blocks inside Markdown; run `ruff format --check .` after editing docs.
- `pg_locks` is cluster-wide: filter by `current_database()`, or a parallel test run breaks the test.
- The pre-commit hook runs the full gate on the working tree, not only the staged files.

## Output Contract

Report to the owner: outcome, every failed, skipped or pending check, the commits, the `Risk:` line, and the next step (PR, phase report). Never push or open a PR without the owner's approval.

## References

- `../../../AGENTS.md` — rules: quality gate, TDD, branches, PRs, commits.
- `../../../docs/process/phase-review.md` — phase review checklist and severity.
- `../../../docs/roadmap/README.md` — phase status.
