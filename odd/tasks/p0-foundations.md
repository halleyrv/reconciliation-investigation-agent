# P0 Foundations

Objective: a repository with a working quality gate, ready for Phase 1. Spec: `docs/roadmap/phase-0-foundations.md` (including its 2026-11-09 CI amendment).
Branch: `feat/p0-foundations`. Delivery: one draft PR after the CI task, phase review on it, owner merges. Test runner: `pytest` through `uv run --locked` (from T3 on; none before).

## Specs

Quoted verbatim from the phase file.

- **S1** "**Git:** initialize the repository with a `.gitignore`. Make a first commit with the existing documentation (`AGENTS.md`, `CLAUDE.md`, `docs/`) on `main`, then develop this phase on `feat/p0-foundations`."
- **S2** "**Verified environment:** record the actual versions of macOS, Python, `uv` and Docker available on the owner's machine, with the date. Do not assume versions."
- **S3** "**Python workspace with `uv`:** pinned Python version, `uv.lock` committed, and a `simulator/` package skeleton ready for Phase 1."
- **S4** "**Tooling:** `ruff` (format + lint), `mypy` in strict mode, `pytest`."
- **S5** "**Import contracts with `import-linter`:** the simulator must not import the backend, LangGraph or any LLM SDK."
- **S6** "**Quality gate:** `scripts/check.sh` runs format check, lint, import contracts, type checks and tests through `uv run --locked`. It stops at the first failure with a non-zero exit code. A git pre-commit hook (via `core.hooksPath`) runs the same script."
- **S7** "**Negative proof:** introduce a forbidden import on purpose (never committed) and show that both `scripts/check.sh` and the pre-commit hook fail and block the commit. Remove it and show the gate is green again."
- **S8** "**Documentation:** `README.md` with the commands that were actually executed (setup, check, hook installation). Update `AGENTS.md` with the real commands."
- **S9** (amendment) "**Requirement 9 — CI (GitHub Actions):** one workflow that installs `uv` and runs `scripts/check.sh`, on every push and every pull request. The workflow has no checks of its own: `scripts/check.sh` stays the single definition of the quality gate."

Acceptance criteria (verbatim):

| ID | Criterion |
|----|-----------|
| AC1 | `scripts/check.sh` passes on a clean tree with at least one example test |
| AC2 | With the deliberate forbidden import, `scripts/check.sh` fails and names the broken contract |
| AC3 | With the same violation staged, `git commit` is blocked by the pre-commit hook and `HEAD` does not move |
| AC4 | `uv run --locked` works from a fresh clone, with no undeclared dependencies |
| AC5 | `README.md` and `AGENTS.md` list only commands that were actually run |
| AC6 | No secrets in the repository |
| AC7 | CI runs `scripts/check.sh` on every push and pull request. It is green on the clean tree. A throwaway branch carrying the deliberate forbidden import from AC2 makes CI fail and name the broken contract. The branch is deleted afterwards and never merged |

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1 | inline | done | `29965be` on `main`; branch `feat/p0-foundations` created and pushed |
| T2 | S2 | inline | done | Environment table in Log L3 |
| T3 | S3 | inline | done | `.python-version` = `3.14`, `uv.lock`, `simulator/` src-layout package (L5) |
| T4 | S4, AC1 | inline | done | ruff, mypy strict, pytest configured; example test passes (L6) |
| T5 | S5 | inline | pending | — |
| T6 | S6, AC1, AC4 | inline | pending | — |
| T7 | S7, AC2, AC3 | inline | pending | — |
| T8 | S8, AC5, AC6 | inline | pending | — |
| T9 | S9, AC7 | inline | pending | — |
| T10 | Phase review | independent reviewer | pending | — |

Route: every task is inline; no writer trigger applies (one sequential unit of setup, each step depends on the previous).

## Log

- **L1** (2026-11-09, owner) "dale, arrancá con la Fase 0"
- **L2** (2026-11-09) Quality gate: `scripts/check.sh` does not exist yet, so there is no gate to run before starting. It is created in T6. Docs-only commits before this phase started: `29965be`, `7955b96`, `2c50565`, `9bfd976`. Remote: `github.com/halleyrv/reconciliation-investigation-agent` (public).
- **L3** (2026-11-09) Verified environment, from commands run on the owner's machine:

  | Tool | Version | Command |
  |------|---------|---------|
  | macOS | 26.7.1 (build 25G241), `x86_64` (Intel) | `sw_vers`, `uname -m` |
  | `uv` | 0.12.5 (Homebrew) | `uv --version` |
  | Python on `PATH` | 3.6.15 (pyenv shim, not usable for this project) | `python3 --version` |
  | Pythons found by `uv` | 3.15.1, 3.14.8, 3.14.7, 3.13.15, 3.12.2, 3.11.8 | `uv python list --only-installed` |
  | Docker | 29.4.0 | `docker --version` |
  | Docker Compose | v5.1.2 | `docker compose version` |

- **L4** (2026-11-09) Open decision for the owner: which Python version to pin (T3). The machine is Intel (`x86_64`), which matters for the local embedding and reranker models of ADR-0006 in Phase 3. Waiting for the owner.
- **L5** (2026-11-09, owner) "dale, borrá la línea y seguimos con 3.14.8". Decision: Python 3.14. Tradeoff accepted: no native Intel-Mac wheels for `torch` (last 2.2.2, up to 3.12) or `onnxruntime` (last 1.23.2, up to 3.13), so Phase 3 local models run in Linux containers. `.python-version` pins `3.14` (not `3.14.8`): uv 0.12.5 only downloads up to 3.14.7, so an exact pin could break a fresh clone or CI (AC4). Local venv built on pyenv 3.14.8 (`uv venv --python 3.14.8`). Owner shell fix outside the repo: removed `pyenv global 3.6.15` from line 17 of `~/.zshrc` (backup `~/.zshrc.bak-2026-11-09`), set `pyenv global 3.14.8`.
- **L6** (2026-11-09) Tooling versions locked: ruff 0.17.4, mypy 2.4.1+, pytest 9.2.0+, import-linter 2.16+. Observed: `ruff format --check .` (34 files, ruff also formats Python blocks inside Markdown), `ruff check .` passed, `lint-imports` 1 kept 0 broken, `mypy` no issues in 2 files, `pytest -q` 1 passed. TDD exception: configuration with no business behavior; the first test run failed only because `--import-mode=importlib` named the test module `simulator.tests.test_package` and shadowed the real `simulator` package, fixed by dropping that option.
