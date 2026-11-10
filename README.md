# AI Reconciliation & Investigation Agent

An AI-powered financial reconciliation and investigation system. It ingests records from independent sources (orders, payment gateway transactions, bank statements, refunds, fees and authorizations), detects discrepancies with a deterministic engine, investigates them with a LangGraph agent backed by hybrid RAG, and proposes resolutions that a human must approve.

All data is synthetic, produced by an independent Financial Data Simulator. No real customer or financial data is used.

## Status

Phases 0 (foundations) and 1 ([Financial Data Simulator](simulator/README.md)) are done. Phase 2 (backend and reconciliation engine) is in progress: sub-phase 2a, ingestion, is done (see [backend/README.md](backend/README.md)); 2b, the reconciliation engine, is next. See the [roadmap](docs/roadmap/README.md) for every phase and its status.

## Setup

Requirements: [`uv`](https://docs.astral.sh/uv/) (verified with 0.12.5) and Docker with Compose (verified with Docker 29.4.0), which runs PostgreSQL for the backend tests. Python 3.14 is pinned in `.python-version`; `uv` uses an installed 3.14 or downloads one.

```bash
git clone https://github.com/halleyrv/reconciliation-investigation-agent.git
cd reconciliation-investigation-agent
uv sync --locked                          # install the locked environment
git config core.hooksPath .githooks       # run the quality gate before every commit
```

## Quality gate

```bash
scripts/check.sh
```

It runs format check, lint, import contracts and type checks, starts the Compose PostgreSQL (`docker compose up -d --wait db`), runs the tests through `uv run --locked`, and stops at the first failure. The pre-commit hook and CI run the same script.

## Principles

- PostgreSQL is the source of truth.
- Financial calculations and transaction matching are deterministic. The LLM never does arithmetic or matching.
- The LLM never invents transactions, approvals or evidence, and every conclusion references its evidence.
- Every consequential action requires explicit human approval.
- Every operation is idempotent and every case has an auditable history.

## Documentation

| Topic | Document |
|-------|----------|
| Product brief | [docs/product-brief.md](docs/product-brief.md) |
| Roadmap and phase specs | [docs/roadmap/](docs/roadmap/README.md) |
| Architecture | [docs/architecture/](docs/architecture/README.md) |
| Architecture decisions (ADRs) | [docs/adr/](docs/adr/README.md) |
| Phase review process | [docs/process/phase-review.md](docs/process/phase-review.md) |
| Financial Data Simulator | [simulator/README.md](simulator/README.md) |
| Instructions for coding agents | [AGENTS.md](AGENTS.md) |
