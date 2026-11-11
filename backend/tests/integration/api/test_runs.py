"""``POST /reconciliation-runs`` and ``GET /reconciliation-runs/{id}`` (S2, AC-2c.4)."""

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.integration.api.conftest import OCTOBER, assert_problem, scalar

WRITES = (
    "SELECT (SELECT count(*) FROM recon.reconciliation_runs)"
    " + (SELECT count(*) FROM recon.discrepancies) + (SELECT count(*) FROM recon.match_groups)"
    " + (SELECT count(*) FROM recon.outbox) + (SELECT count(*) FROM investigation.cases)"
    " + (SELECT count(*) FROM audit.events)"
)


def test_post_runs_the_period_and_delivers_its_events(
    reconciled: dict[str, Any], engine: Engine
) -> None:
    run = reconciled

    assert run["period"] == OCTOBER
    assert run["ruleset_version"] == "v1"
    assert run["status"] == "completed"
    assert run["started_at"] and run["finished_at"]
    assert scalar(engine, "SELECT status FROM recon.reconciliation_runs") == "completed"
    assert str(scalar(engine, "SELECT id FROM recon.reconciliation_runs")) == run["id"]
    # delivered in-process like the CLI: every discrepancy has its case and its audit entry
    assert scalar(engine, "SELECT count(*) FROM investigation.cases") == 41
    assert scalar(engine, "SELECT count(*) FROM recon.outbox WHERE published_at IS NULL") == 0
    assert (
        scalar(engine, "SELECT DISTINCT actor_id FROM recon.outbox WHERE actor_type = 'system'")
        == "api"
    )


def test_reposting_the_period_returns_the_same_run_and_writes_nothing(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    before = scalar(engine, WRITES)

    again = imported.post("/reconciliation-runs", json=OCTOBER)

    assert again.status_code == 200
    assert again.json() == reconciled
    assert scalar(engine, WRITES) == before


def test_get_run_returns_it_with_its_summary(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    response = imported.get(f"/reconciliation-runs/{reconciled['id']}")

    assert response.status_code == 200
    body = response.json()
    summary = body.pop("summary")
    assert body == reconciled
    assert summary["match_groups"] == scalar(engine, "SELECT count(*) FROM recon.match_groups")
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT type, count(*) FROM recon.discrepancies GROUP BY type")
        )
        per_type = {row.type: row.count for row in rows}
    assert summary["discrepancies"] == per_type
    assert sum(summary["discrepancies"].values()) == 41


def test_get_unknown_run_is_404(client: TestClient) -> None:
    assert_problem(client.get(f"/reconciliation-runs/{uuid.uuid4()}"), 404)


def test_an_overlapping_period_is_409(reconciled: dict[str, Any], imported: TestClient) -> None:
    response = imported.post(
        "/reconciliation-runs", json={"from": "2026-10-15", "to": "2026-11-05"}
    )

    body = assert_problem(response, 409)
    assert "overlaps" in body["detail"]


def test_a_period_whose_bank_data_is_incomplete_is_409(
    imported: TestClient, engine: Engine
) -> None:
    response = imported.post(
        "/reconciliation-runs", json={"from": "2026-12-01", "to": "2026-12-31"}
    )

    body = assert_problem(response, 409)
    assert "not closed" in body["detail"]
    assert scalar(engine, "SELECT count(*) FROM recon.reconciliation_runs") == 0


def test_a_run_still_running_is_409(imported: TestClient, engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recon.reconciliation_runs (id, period, ruleset_version, status,"
                " started_at) VALUES (gen_random_uuid(), '[2026-10-01,2026-11-01)', 'v1',"
                " 'running', now())"
            )
        )

    body = assert_problem(imported.post("/reconciliation-runs", json=OCTOBER), 409)

    assert "still running" in body["detail"]


def test_a_period_ending_before_it_starts_is_422(client: TestClient, engine: Engine) -> None:
    response = client.post("/reconciliation-runs", json={"from": "2026-10-31", "to": "2026-10-01"})

    assert_problem(response, 422)
    assert scalar(engine, "SELECT count(*) FROM recon.reconciliation_runs") == 0


def test_a_malformed_period_is_422_with_field_errors(client: TestClient) -> None:
    body = assert_problem(client.post("/reconciliation-runs", json={"from": "October"}), 422)

    assert {e["loc"][-1] for e in body["errors"]} == {"from", "to"}


def test_a_failed_run_is_422_with_its_id(imported: TestClient, engine: Engine) -> None:
    # no reference data loaded: the run starts, then refuses to report unchecked fees
    body = assert_problem(imported.post("/reconciliation-runs", json=OCTOBER), 422)

    assert body["run_id"] == str(scalar(engine, "SELECT id FROM recon.reconciliation_runs"))
    assert scalar(engine, "SELECT status FROM recon.reconciliation_runs") == "failed"
    assert "load it first" in body["detail"]
