"""``POST /imports`` and ``GET /imports/{id}`` (S2, AC-2c.4)."""

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from recon.bootstrap.app import create_app
from tests.integration.api.conftest import assert_problem, scalar

COUNTS = (
    "SELECT (SELECT count(*) FROM ingestion.import_batches)"
    " + (SELECT count(*) FROM ingestion.raw_records) + (SELECT count(*) FROM ingestion.outbox)"
)


def _batches(engine: Engine) -> int:
    return int(scalar(engine, "SELECT count(*) FROM ingestion.import_batches"))


def _break_fees(sample: Path) -> None:
    """Make fees.json fail validation while still matching the manifest."""
    fees = sample / "fees.json"
    fees.write_text(json.dumps({"record_type": "fees", "records": [{"id": 1}]}))
    manifest = json.loads((sample / "manifest.json").read_text())
    manifest["files"]["fees.json"] = hashlib.sha256(fees.read_bytes()).hexdigest()
    (sample / "manifest.json").write_text(json.dumps(manifest))


def test_import_returns_every_batch_and_stores_them(
    client: TestClient, engine: Engine, sample: Path
) -> None:
    response = client.post("/imports", json={"directory": str(sample)})

    assert response.status_code == 200
    batches = response.json()
    assert len(batches) == 7 == _batches(engine)
    assert {b["status"] for b in batches} == {"completed"}
    orders = next(b for b in batches if b["record_type"] == "orders")
    assert orders["file_name"] == "orders.json"
    assert orders["source"]
    stored = "SELECT count(*) FROM ingestion.raw_records WHERE batch_id = :id"
    assert orders["row_count"] == scalar(engine, stored, id=orders["id"]) > 0
    assert orders["errors"] == []
    uuid.UUID(orders["id"])


def test_reposting_the_same_directory_returns_the_same_batches_and_writes_nothing(
    client: TestClient, engine: Engine, sample: Path
) -> None:
    first = client.post("/imports", json={"directory": str(sample)}).json()
    before = scalar(engine, COUNTS)

    second = client.post("/imports", json={"directory": str(sample)})

    assert second.status_code == 200
    assert second.json() == first
    assert scalar(engine, COUNTS) == before


def test_a_rejected_file_is_a_failed_batch_with_its_errors(
    client: TestClient, engine: Engine, sample: Path
) -> None:
    _break_fees(sample)

    batches = client.post("/imports", json={"directory": str(sample)}).json()

    fees = next(b for b in batches if b["record_type"] == "fees")
    assert fees["status"] == "failed"
    assert fees["row_count"] == 0
    assert fees["errors"]
    assert set(fees["errors"][0]) == {"file", "line", "field", "message"}
    assert fees["errors"][0]["file"] == "fees.json"


def test_get_import_returns_the_batch_with_its_stored_errors(
    client: TestClient, sample: Path
) -> None:
    _break_fees(sample)
    batches = client.post("/imports", json={"directory": str(sample)}).json()
    fees = next(b for b in batches if b["record_type"] == "fees")
    orders = next(b for b in batches if b["record_type"] == "orders")

    assert client.get(f"/imports/{fees['id']}").json() == fees
    assert client.get(f"/imports/{orders['id']}").json() == orders


def test_get_unknown_import_is_404(client: TestClient) -> None:
    body = assert_problem(client.get(f"/imports/{uuid.uuid4()}"), 404)

    assert "import batch" in body["detail"]


def test_get_import_with_a_malformed_id_is_422(client: TestClient) -> None:
    body = assert_problem(client.get("/imports/not-a-uuid"), 422)

    assert body["errors"]


def test_missing_directory_field_is_422_with_field_errors(
    client: TestClient, engine: Engine
) -> None:
    body = assert_problem(client.post("/imports", json={}), 422)

    assert any(e["loc"][-1] == "directory" for e in body["errors"])
    assert _batches(engine) == 0


@pytest.mark.parametrize("escape", ["..", "../.."])
def test_a_directory_outside_the_import_root_is_422_and_nothing_is_read(
    client: TestClient, engine: Engine, sample: Path, tmp_path: Path, escape: str
) -> None:
    outside = tmp_path / escape / "elsewhere"

    body = assert_problem(client.post("/imports", json={"directory": str(outside)}), 422)

    assert "RECON_IMPORT_ROOT" in body["detail"]
    assert _batches(engine) == 0


def test_an_export_outside_the_root_is_not_imported(
    engine: Engine, sample: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("RECON_IMPORT_ROOT", str(root))
    with TestClient(create_app(engine=engine)) as client:
        response = client.post("/imports", json={"directory": str(root / ".." / "export")})

    assert_problem(response, 422)
    assert _batches(engine) == 0


def test_without_an_import_root_nothing_is_imported(
    engine: Engine, sample: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RECON_IMPORT_ROOT", raising=False)
    with TestClient(create_app(engine=engine)) as client:
        response = client.post("/imports", json={"directory": str(sample)})

    body = assert_problem(response, 422)
    assert "RECON_IMPORT_ROOT" in body["detail"]
    assert _batches(engine) == 0


def test_a_directory_that_is_not_an_export_is_422(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    (tmp_path / "empty").mkdir()

    assert_problem(client.post("/imports", json={"directory": str(tmp_path / "empty")}), 422)
    assert _batches(engine) == 0


def test_a_manifest_mismatch_is_422_and_nothing_is_imported(
    client: TestClient, engine: Engine, sample: Path
) -> None:
    (sample / "orders.json").write_bytes((sample / "orders.json").read_bytes() + b" ")

    body = assert_problem(client.post("/imports", json={"directory": str(sample)}), 422)

    assert "orders.json" in body["detail"]
    assert _batches(engine) == 0
