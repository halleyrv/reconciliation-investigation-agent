"""The HTTP API against the Compose PostgreSQL. ``RECON_IMPORT_ROOT`` is the test's ``tmp_path``,
which holds the ``sample`` export."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from recon.bootstrap.app import create_app
from recon.bootstrap.cli import reference_main

REFERENCE_FILE = Path(__file__).parents[3] / "reference" / "gateway-policy-2026.json"
OCTOBER = {"from": "2026-10-01", "to": "2026-10-31"}


def scalar(engine: Engine, sql: str, **params: object) -> Any:
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar_one()


def assert_problem(response: Any, status: int) -> dict[str, Any]:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body: dict[str, Any] = response.json()
    assert body["type"] == "about:blank"
    assert body["status"] == status
    assert body["title"]
    assert "Traceback" not in response.text
    return body


def second_run(engine: Engine, first_run: str) -> str:
    """A second run's copy of every discrepancy, inserted with fresh random IDs; its ID."""
    with engine.begin() as connection:
        second = connection.execute(
            text(
                "INSERT INTO recon.reconciliation_runs (id, period, ruleset_version, status,"
                " started_at, finished_at) VALUES (gen_random_uuid(), '[2027-01-01,2027-02-01)',"
                " 'v1', 'completed', now(), now()) RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO recon.discrepancies (id, run_id, type, severity, expected_minor,"
                " actual_minor, currency, fingerprint, status, detected_at)"
                " SELECT gen_random_uuid(), :second, type, severity, expected_minor,"
                " actual_minor, currency, fingerprint, status, now()"
                " FROM recon.discrepancies WHERE run_id = :first"
            ),
            {"first": first_run, "second": second},
        )
        return str(second)


@pytest.fixture
def client(engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("RECON_IMPORT_ROOT", str(tmp_path))
    with TestClient(create_app(engine=engine), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def imported(client: TestClient, sample: Path) -> TestClient:
    assert client.post("/imports", json={"directory": str(sample)}).status_code == 200
    return client


@pytest.fixture
def reconciled(
    imported: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """The October run of the seed-42 export, with its reference data loaded."""
    monkeypatch.setenv("RECON_DATABASE_URL", migrated_url)
    assert reference_main([str(REFERENCE_FILE)]) == 0
    response = imported.post("/reconciliation-runs", json=OCTOBER)
    assert response.status_code == 200
    run: dict[str, Any] = response.json()
    return run
