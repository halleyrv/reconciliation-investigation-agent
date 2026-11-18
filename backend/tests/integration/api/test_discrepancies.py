"""``GET /discrepancies``: filters and keyset pagination (S2, AC-2c.3, AC-2c.4)."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.integration.api.conftest import assert_problem, scalar, second_run

ITEM_KEYS = {
    "id",
    "run_id",
    "type",
    "severity",
    "expected_minor",
    "actual_minor",
    "delta_minor",
    "currency",
    "status",
    "detected_at",
}


def _ids(engine: Engine, where: str = "TRUE", **params: object) -> list[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(f"SELECT id FROM recon.discrepancies WHERE {where} ORDER BY id"), params
        )
        return [str(r.id) for r in rows]


def _walk(client: TestClient, limit: int, **filters: str | int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    while True:
        params = {**filters, "limit": limit} | ({"cursor": cursor} if cursor else {})
        response = client.get("/discrepancies", params=params)
        assert response.status_code == 200
        page = response.json()
        items += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            return items


def test_an_unfiltered_list_returns_every_discrepancy_ordered_by_id(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    page = imported.get("/discrepancies").json()

    assert [i["id"] for i in page["items"]] == _ids(engine)
    assert page["next_cursor"] is None
    item = page["items"][0]
    assert set(item) == ITEM_KEYS
    assert item["run_id"] == reconciled["id"]
    assert item["delta_minor"] == item["actual_minor"] - item["expected_minor"]
    assert item["status"] == "detected"


def test_filter_by_run(reconciled: dict[str, Any], imported: TestClient, engine: Engine) -> None:
    second_run(engine, reconciled["id"])

    items = _walk(imported, 200, run_id=reconciled["id"])

    assert [i["id"] for i in items] == _ids(engine, "run_id = :r", r=reconciled["id"])
    assert len(items) == 41


def test_filter_by_type(reconciled: dict[str, Any], imported: TestClient, engine: Engine) -> None:
    items = _walk(imported, 200, type="fee_mismatch")

    assert [i["id"] for i in items] == _ids(engine, "type = 'fee_mismatch'")
    assert items


def test_filter_by_severity(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    items = _walk(imported, 200, severity="high")

    assert [i["id"] for i in items] == _ids(engine, "severity = 'high'")
    assert items


def test_filter_by_minimum_absolute_delta(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    items = _walk(imported, 200, min_abs_delta=1000)

    assert [i["id"] for i in items] == _ids(engine, "abs(delta_minor) >= 1000")
    assert 0 < len(items) < 41
    assert all(abs(i["delta_minor"]) >= 1000 for i in items)


def test_filters_combine(reconciled: dict[str, Any], imported: TestClient, engine: Engine) -> None:
    second_run(engine, reconciled["id"])
    severity = scalar(
        engine, "SELECT min(severity) FROM recon.discrepancies WHERE abs(delta_minor) >= 1"
    )

    items = _walk(imported, 3, run_id=reconciled["id"], severity=severity, min_abs_delta=1)

    assert [i["id"] for i in items] == _ids(
        engine,
        "run_id = :r AND severity = :s AND abs(delta_minor) >= 1",
        r=reconciled["id"],
        s=severity,
    )
    assert items


def test_walking_pages_returns_each_row_once_while_rows_are_inserted(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    before = set(_ids(engine))
    first = imported.get("/discrepancies", params={"limit": 7}).json()
    second_run(engine, reconciled["id"])

    rest: list[dict[str, Any]] = []
    cursor = first["next_cursor"]
    while cursor is not None:
        page = imported.get("/discrepancies", params={"limit": 7, "cursor": cursor}).json()
        rest += page["items"]
        cursor = page["next_cursor"]

    walked = [i["id"] for i in first["items"] + rest]
    assert len(first["items"]) == 7
    assert len(walked) == len(set(walked))
    assert before <= set(walked)
    assert walked == sorted(walked)


@pytest.mark.parametrize(
    "params",
    [
        {"type": "not_a_type"},
        {"severity": "critical"},
        {"min_abs_delta": -1},
        {"limit": 0},
        {"limit": 201},
        {"run_id": "nope"},
    ],
)
def test_an_invalid_filter_is_422_with_field_errors(
    client: TestClient, params: dict[str, str | int]
) -> None:
    body = assert_problem(client.get("/discrepancies", params=params), 422)

    assert body["errors"][0]["loc"][-1] == next(iter(params))


@pytest.mark.parametrize("cursor", ["!!!", "bm90LWEtdXVpZA", uuid.uuid4().hex])
def test_a_malformed_cursor_is_422(client: TestClient, cursor: str) -> None:
    body = assert_problem(client.get("/discrepancies", params={"cursor": cursor}), 422)

    assert "cursor" in body["detail"]
