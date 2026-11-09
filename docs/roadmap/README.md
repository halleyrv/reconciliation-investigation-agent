# Roadmap

All phases start as pending. A phase is never marked done just because files were generated: it needs every acceptance criterion proven, with evidence in its ODD document.

## How this folder works

| File | Written by | Purpose |
|------|-----------|---------|
| `phase-N-<name>.md` | Project owner | The phase as requested, kept verbatim. Never rewritten by the agent. Later changes the owner approves are appended in an `Amendments` table with their date |
| `README.md` (this file) | Agent, kept up to date | Index: status of each phase and link to its ODD document |
| `odd/tasks/pN-<name>.md` | Agent, when the phase starts | Tasks, acceptance evidence and log (Gentle AI ODD format) |

- **Statuses:** `pending`, `in progress`, `blocked (<reason>)`, `deferred (<reason>)`, `done`.
- **Sub-phases:** scope added inside a phase gets its own file (`phase-2b-<name>.md`) without renumbering the others.
- **Decisions** taken during a phase go to [`docs/adr/`](../adr/README.md). The phase only links to them.
- A phase starts only after the previous phase is reported to the owner.

## Phases

| Phase | Goal | Status | Spec | Detail |
|-------|------|--------|------|--------|
| 0 | Foundations: git, uv workspace, tooling, quality gate | done | [phase-0](phase-0-foundations.md) | [p0-foundations](../../odd/tasks/p0-foundations.md) |
| 1 | Financial Data Simulator | in progress | [phase-1](phase-1-financial-data-simulator.md) | [p1-financial-data-simulator](../../odd/tasks/p1-financial-data-simulator.md) |
| 2 | Backend and reconciliation engine (2a ingestion, 2b engine + evaluation, 2c cases, audit, API) | pending | [phase-2](phase-2-backend-and-reconciliation-engine.md) | — |
| 3 | Hybrid RAG and evidence verification | pending | [phase-3](phase-3-hybrid-rag-and-evidence-verification.md) | — |
| 4 | LangGraph investigation agent | pending | [phase-4](phase-4-langgraph-investigation-agent.md) | — |
| 5 | Resolution and human approval | pending | [phase-5](phase-5-resolution-and-human-approval.md) | — |
| 6 | Evaluation and benchmarking | pending | [phase-6](phase-6-evaluation-and-benchmarking.md) | — |
| 7 | Frontend and product experience | pending | [phase-7](phase-7-frontend-and-product-experience.md) | — |
| 8 | Reliability, deployment and final review | pending | [phase-8](phase-8-reliability-deployment-and-final-review.md) | — |

Phase files 3, 4 and 6–8 keep their original headings verbatim; their `Amendments` table records the renumbering.

## Future ideas (out of MVP)

None yet.
