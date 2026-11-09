# AGENTS.md

Entry point for any coding agent (Claude Code, Codex, others) working in this repository. Read this file first, then follow the links. Detail lives in the linked documents and is not repeated here.

## Project in one paragraph

An AI-powered financial reconciliation and investigation system. It ingests records from independent sources (orders, payment gateway transactions, bank statements, refunds, fees, authorizations). A deterministic engine detects discrepancies. A LangGraph agent investigates them with hybrid RAG and proposes resolutions, and humans approve every consequential action. All data is synthetic and produced by an independent Financial Data Simulator. This is a production-oriented portfolio project: write code at Staff/Senior level, not tutorial level.

## Where things are

| Need | Read |
|------|------|
| **Start here:** product vision, required stack, principles and development strategy (owner's brief, verbatim) | [`docs/product-brief.md`](docs/product-brief.md) |
| What to build next and phase status | [`docs/roadmap/README.md`](docs/roadmap/README.md) |
| The owner's spec for a phase (verbatim + amendments) | `docs/roadmap/phase-N-<name>.md` |
| Tasks, evidence and log of the active phase | `odd/tasks/pN-<name>.md` (Gentle AI ODD document) |
| Architecture standards and rules | [`docs/architecture/README.md`](docs/architecture/README.md) |
| Bounded contexts, aggregates, events | [`docs/architecture/bounded-contexts.md`](docs/architecture/bounded-contexts.md) |
| Relational model and denormalization register | [`docs/architecture/data-model.md`](docs/architecture/data-model.md) |
| Folder layout, layer rules, port inventory | [`docs/architecture/project-structure.md`](docs/architecture/project-structure.md) |
| How a phase is reviewed before it closes | [`docs/process/phase-review.md`](docs/process/phase-review.md) |
| Why a decision was made | [`docs/adr/README.md`](docs/adr/README.md) (index with area and one-line decision) |

## Non-negotiable principles

1. PostgreSQL is the source of truth.
2. Financial calculations are deterministic.
3. Never delegate arithmetic or transaction matching to an LLM.
4. The LLM must not invent transactions, approvals or evidence.
5. Every investigation conclusion references supporting evidence.
6. Every consequential action requires explicit human approval.
7. All operations handle retries and idempotency.
8. Every case has an auditable history.
9. Agent execution is observable.
10. Missing or contradictory information is handled gracefully.
11. Never use real customer or financial data.

## Engineering standards (ADR-0010)

- **Data:** 3NF minimum. Every denormalization has an entry in the register in `data-model.md`. JSONB only for snapshots, event payloads and transport messages.
- **DDD:** one PostgreSQL schema per bounded context. A context writes only to its own schema. Invariants live in aggregates.
- **Hexagonal:** `domain` → stdlib + `shared_kernel` only. SQLAlchemy, LangGraph, FastAPI, Pydantic and LLM SDKs live only in `adapters`. A port exists only with a named reason in the port inventory.
- **SOLID:** composition over inheritance. No generic `Repository[T]`. Repositories expose business-named methods.
- **Money:** never `float`. `Decimal` in the simulator, integer minor units + currency in the backend (ADR-0002).

## How work flows

1. The owner writes a phase in `docs/roadmap/phase-N-<name>.md`. Agents never rewrite it; approved changes go to its `Amendments` table.
2. When a phase starts, the agent creates its ODD document in `odd/tasks/` and splits the phase into tasks.
3. Work goes task by task. A task is `done` only with evidence: a passing test and a commit. Generating files is not evidence.
4. A phase is `done` only when every acceptance criterion is proven and the [phase review](docs/process/phase-review.md) has run with its critical and high findings fixed. The agent reports the phase result to the owner **before** starting the next one.
5. Any decision with real alternatives gets an ADR in `docs/adr/`, added to the index in the same change. Accepted ADRs are never edited, only superseded.
6. Decisions marked `Proposed` need the owner's approval before anything that depends on them is built.

## Quality gate: `scripts/check.sh`

One script validates that the repository works: formatting, lint, import contracts, type checks and the full test suite. It is the same check everywhere: locally, in the git pre-commit hook and in CI.

1. **Before starting a task:** run `scripts/check.sh` on the phase branch. If it fails, fixing it is the first job, in its own commit, before any work on the task begins. Never build on a red baseline.
2. **Before closing a task:** run `scripts/check.sh` again. A task is not done while it fails.
3. **Never bypass it:** no `--no-verify`, no skipped or deleted tests to get green. A failure you cannot fix is reported to the owner as a blocker.
4. **Branches:** each phase is developed on its own branch (`feat/pN-<name>`), never directly on `main`.

Commands (run on this repository):

```bash
uv sync --locked                          # install the locked environment
git config core.hooksPath .githooks       # enable the pre-commit hook (once per clone)
scripts/check.sh                          # run the full gate
```

Steps of the gate, in order: `ruff format --check .`, `ruff check .`, `lint-imports`, `mypy`, `pytest -q`, each through `uv run --locked`. Import contracts live in `[tool.importlinter]` in the root `pyproject.toml`.

## Testing: TDD is mandatory

Every behavior change follows Test-Driven Development. The test is written **before** the code.

1. **RED:** write a test for the behavior and run it. It must fail for the expected reason (missing behavior), not because of a typo or broken setup.
2. **GREEN:** write the minimum code that makes the test pass.
3. **REFACTOR:** clean up the code while every test stays green.

Rules:

- Record the RED and GREEN evidence (the command and its relevant output) in the task's entry in the ODD document. A task without RED evidence is not done.
- One test per business rule, through the public interface (use case, API, simulator CLI), asserting every observable effect: return value, persisted data, emitted events, errors.
- A bug fix starts with a test that reproduces the bug.
- Only exceptions: documentation and configuration changes with no runnable behavior. The task log states the exception and how the change was checked instead.

Test types:

- Domain and application tests use no database and no network (in-memory fakes of ports).
- Adapter tests run against a real PostgreSQL.
- Simulator output must be reproducible: same seed and config produce byte-identical output.
- Run the tests: `uv run --locked pytest -q`, or one file with `uv run --locked pytest -q <path>`.

## Conventions

- **Language:** code, comments, docs, commit messages and UI copy in English. Talk to the owner in the language they use.
- **Commits:** Conventional Commits. Every commit except `docs`, `style` and `chore` has a body explaining why. No AI attribution or `Co-Authored-By` lines.
- **Secrets:** never in the repository. `.env.example` lists names only.
- **Scope:** do not implement anything a phase did not ask for. Name what you skipped instead.
