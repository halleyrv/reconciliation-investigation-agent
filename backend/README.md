# Backend

The reconciliation backend: a modular monolith (ADR-0001) with one package and one PostgreSQL schema per bounded context. Phase 2a delivers the **Ingestion** context: it imports a simulator export into typed canonical tables, idempotently and in one transaction per file. Phase 2b adds the **Reconciliation** context (in progress): reference data, the deterministic matching engine and its runs.

Architecture rules live in [`docs/architecture/`](../docs/architecture/README.md); the 2a tasks and evidence in [`odd/tasks/p2a-ingestion.md`](../odd/tasks/p2a-ingestion.md).

## Run it

Every command below runs from the repository root and was run while building 2a and 2b.

```bash
docker compose up -d --wait db                          # PostgreSQL 18 + pgvector on 127.0.0.1:55432
uv run --locked alembic -c backend/alembic.ini upgrade head
uv run --locked recon-import simulator/samples/orders-200-seed-42
uv run --locked recon-reference backend/reference/gateway-policy-2026.json
uv run --locked alembic -c backend/alembic.ini downgrade base
```

`recon-import` prints one line per file:

```text
orders.json: completed, 204 records
payments.json: completed, 206 records
...
```

| Exit code | Meaning |
|-----------|---------|
| 0 | Every file completed (also when every file was already imported) |
| 1 | At least one file was rejected; each error shows its line and field |
| 2 | Nothing was imported: a file differs from `manifest.json` or is missing |

`recon-reference` loads the fee schedules and bank holidays the engine applies. An operator transcribes them by hand from the gateway's published policy into [`reference/gateway-policy-2026.json`](reference/gateway-policy-2026.json); a test checks that file against the policy text, and no code parses the policy (OD1). Loading is idempotent:

```text
fee schedules: 2 added, 0 already loaded
holidays: 7 added, 0 already loaded
```

| Exit code | Meaning |
|-----------|---------|
| 0 | Loaded, or already loaded |
| 1 | Nothing loaded: a fee schedule overlaps a different one already loaded for the same gateway and fee type |
| 2 | Nothing loaded: the file is missing or does not match the format |

The database URL comes from `RECON_DATABASE_URL` (default: the Compose database, which uses trust auth on loopback and has no password).

## What an import guarantees

| Rule | How |
|------|-----|
| Files match the export | Every file's SHA-256 is checked against `manifest.json` before any row is written |
| A file is imported once per source | Re-importing returns the existing batch; the database enforces `UNIQUE (source_id, file_sha256)` |
| A record is never overwritten | A re-sent external ID with a different payload creates a `source_conflicts` row and a `SourceConflictDetected` event in `ingestion.outbox`; the first record stays |
| One bad row rejects its whole file | The batch is `failed` with file, line and field, and no records of that file are stored |
| Money is exact | Decimal strings become integer minor units; a JSON number, a negative amount or more than 2 decimals is rejected (ADR-0002) |
| Concurrent imports are safe | Each file's transaction takes an advisory lock for its source |

Only the JSON files are read; their CSV twins carry the same records. In an error, `line` is the record's 1-based position in `records`, and line 0 means the file itself.

## Tests

```bash
uv run --locked pytest -q backend/tests                 # needs the Compose database
```

Unit tests (`backend/tests/unit`) use an in-memory unit of work. Integration tests (`backend/tests/integration`) create a fresh database per session, migrate it and drop it afterwards.
