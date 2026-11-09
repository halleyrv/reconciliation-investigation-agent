# PHASE 0 — Foundations

> Drafted by the agent at the owner's request and **approved by the owner on 2026-11-09**. This text is frozen like any other phase file; later changes go to `Amendments`.

Prepare the repository so Phase 1 (Financial Data Simulator) can be built on a working quality gate. Scope is limited to what Phase 1 needs plus the gate itself. Each later piece of infrastructure arrives with the first phase that uses it.

## Requirements

1. **Git:** initialize the repository with a `.gitignore`. Make a first commit with the existing documentation (`AGENTS.md`, `CLAUDE.md`, `docs/`) on `main`, then develop this phase on `feat/p0-foundations`.
2. **Verified environment:** record the actual versions of macOS, Python, `uv` and Docker available on the owner's machine, with the date. Do not assume versions.
3. **Python workspace with `uv`:** pinned Python version, `uv.lock` committed, and a `simulator/` package skeleton ready for Phase 1.
4. **Tooling:** `ruff` (format + lint), `mypy` in strict mode, `pytest`.
5. **Import contracts with `import-linter`:** the simulator must not import the backend, LangGraph or any LLM SDK.
6. **Quality gate:** `scripts/check.sh` runs format check, lint, import contracts, type checks and tests through `uv run --locked`. It stops at the first failure with a non-zero exit code. A git pre-commit hook (via `core.hooksPath`) runs the same script.
7. **Negative proof:** introduce a forbidden import on purpose (never committed) and show that both `scripts/check.sh` and the pre-commit hook fail and block the commit. Remove it and show the gate is green again.
8. **Documentation:** `README.md` with the commands that were actually executed (setup, check, hook installation). Update `AGENTS.md` with the real commands.

## Acceptance criteria

| ID | Criterion |
|----|-----------|
| AC1 | `scripts/check.sh` passes on a clean tree with at least one example test |
| AC2 | With the deliberate forbidden import, `scripts/check.sh` fails and names the broken contract |
| AC3 | With the same violation staged, `git commit` is blocked by the pre-commit hook and `HEAD` does not move |
| AC4 | `uv run --locked` works from a fresh clone, with no undeclared dependencies |
| AC5 | `README.md` and `AGENTS.md` list only commands that were actually run |
| AC6 | No secrets in the repository |

## Out of scope

| Excluded | Arrives in |
|----------|-----------|
| Docker Compose with PostgreSQL + pgvector, Alembic | Phase 2 (Ingestion), the first phase that writes to the database |
| Backend hexagonal skeleton, FastAPI `/health` | Phase 2 |
| Langfuse | The phase that introduces the investigation agent |
| CI (GitHub Actions) | When the repository has a remote (owner decision) |

---

## Amendments

Changes approved by the owner after the original text above. The original is never edited.

| Date | Change | Approved by |
|------|--------|-------------|
| 2026-11-09 | **CI moves into this phase.** The repository now has a remote (`github.com/halleyrv/reconciliation-investigation-agent`), which was the condition in *Out of scope*. CI is the last task of the phase, built once `scripts/check.sh` exists. Requirement and criterion below. | Owner |

### Amendment 2026-11-09: CI

**Requirement 9 — CI (GitHub Actions):** one workflow that installs `uv` and runs `scripts/check.sh`, on every push and every pull request. The workflow has no checks of its own: `scripts/check.sh` stays the single definition of the quality gate. Services such as PostgreSQL are added in the phase that first needs them (Phase 2).

| ID | Criterion |
|----|-----------|
| AC7 | CI runs `scripts/check.sh` on every push and pull request. It is green on the clean tree. A throwaway branch carrying the deliberate forbidden import from AC2 makes CI fail and name the broken contract. The branch is deleted afterwards and never merged |
