"""``/cases``: open, list, detail, versioned update and history (S2, D1, D2, AC-2c.1,
AC-2c.3, AC-2c.4, AC-2c.5)."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.integration.api.conftest import assert_problem, scalar, second_run

CASE_KEYS = {
    "id",
    "discrepancy_id",
    "status",
    "priority",
    "assignee_id",
    "opened_at",
    "closed_at",
    "version",
}
USER = {"X-Actor-Id": "analyst-7"}


def _case_ids(engine: Engine, where: str = "TRUE", **params: object) -> list[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT c.id FROM investigation.cases c"
                " JOIN recon.discrepancies d ON d.id = c.discrepancy_id"
                f" WHERE {where} ORDER BY c.id"
            ),
            params,
        )
        return [str(r.id) for r in rows]


def _walk(client: TestClient, limit: int, **filters: str | int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    while True:
        params = {**filters, "limit": limit} | ({"cursor": cursor} if cursor else {})
        response = client.get("/cases", params=params)
        assert response.status_code == 200
        page = response.json()
        items += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            return items


def _open_cases_of_run(engine: Engine, run_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO investigation.cases (id, discrepancy_id, status, priority,"
                " opened_at, version) SELECT gen_random_uuid(), id, 'open', severity, now(), 1"
                " FROM recon.discrepancies WHERE run_id = :run"
            ),
            {"run": run_id},
        )


def _a_case(client: TestClient) -> dict[str, Any]:
    case: dict[str, Any] = client.get("/cases", params={"limit": 1}).json()["items"][0]
    return case


def _outbox_rows(engine: Engine) -> int:
    count: int = scalar(engine, "SELECT count(*) FROM investigation.outbox")
    return count


# --- POST /cases ---------------------------------------------------------------------------


def test_every_detected_discrepancy_has_exactly_one_case_after_a_run(
    reconciled: dict[str, Any], engine: Engine
) -> None:
    assert scalar(engine, "SELECT count(*) FROM investigation.cases") == 41
    assert (
        scalar(
            engine,
            "SELECT count(*) FROM recon.discrepancies d"
            " WHERE (SELECT count(*) FROM investigation.cases c"
            " WHERE c.discrepancy_id = d.id) <> 1",
        )
        == 0
    )


def test_the_first_post_opens_the_case_with_201_and_a_second_returns_it_with_200(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    discrepancy = scalar(engine, "SELECT discrepancy_id FROM investigation.cases LIMIT 1")
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM investigation.cases WHERE discrepancy_id = :d"), {"d": discrepancy}
        )

    first = imported.post("/cases", json={"discrepancy_id": str(discrepancy)})
    second = imported.post("/cases", json={"discrepancy_id": str(discrepancy)})

    assert first.status_code == 201
    assert second.status_code == 200
    assert set(first.json()) == CASE_KEYS
    assert second.json() == first.json()
    assert first.json()["status"] == "open"
    assert first.json()["version"] == 1
    assert first.headers["etag"] == '"1"'
    assert (
        scalar(
            engine,
            "SELECT count(*) FROM investigation.cases WHERE discrepancy_id = :d",
            d=discrepancy,
        )
        == 1
    )
    assert (
        scalar(
            engine,
            "SELECT count(*) FROM audit.events"
            " WHERE event_type = 'CaseOpened' AND aggregate_id = :c",
            c=first.json()["id"],
        )
        == 1
    )


def test_posting_an_existing_case_returns_it_and_writes_nothing(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    case = _a_case(imported)
    events = _outbox_rows(engine)

    response = imported.post("/cases", json={"discrepancy_id": case["discrepancy_id"]})

    assert response.status_code == 200
    assert response.json() == case
    assert _outbox_rows(engine) == events


def test_posting_an_unknown_discrepancy_is_404(client: TestClient) -> None:
    body = assert_problem(client.post("/cases", json={"discrepancy_id": str(uuid.uuid4())}), 404)

    assert "discrepancy" in body["detail"]


@pytest.mark.parametrize("body", [{}, {"discrepancy_id": "nope"}])
def test_posting_an_invalid_body_is_422(client: TestClient, body: dict[str, str]) -> None:
    assert_problem(client.post("/cases", json=body), 422)


# --- GET /cases/{id} -----------------------------------------------------------------------


def test_the_detail_holds_the_case_its_discrepancy_and_its_involved_records(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    case = _a_case(imported)
    listed = {
        d["id"]: d for d in imported.get("/discrepancies", params={"limit": 200}).json()["items"]
    }

    response = imported.get(f"/cases/{case['id']}")

    assert response.status_code == 200
    assert response.headers["etag"] == '"1"'
    detail = response.json()
    assert {k: detail[k] for k in CASE_KEYS} == case
    assert detail["discrepancy"] == listed[case["discrepancy_id"]]
    with engine.connect() as connection:
        expected = {
            (kind, str(record_id))
            for kind, record_id in connection.execute(
                text(
                    "SELECT kind, record_id FROM recon.discrepancy_records,"
                    " LATERAL (VALUES ('order', order_id), ('payment', payment_id),"
                    " ('refund', refund_id), ('fee', fee_id), ('settlement', settlement_id),"
                    " ('bank_transaction', bank_transaction_id),"
                    " ('authorization', authorization_id)) AS r(kind, record_id)"
                    " WHERE discrepancy_id = :d AND record_id IS NOT NULL"
                ),
                {"d": case["discrepancy_id"]},
            )
        }
    assert expected
    assert {(r["type"], r["id"]) for r in detail["records"]} == expected
    assert len(detail["records"]) == len(expected)


def test_an_unknown_case_is_404(client: TestClient) -> None:
    assert_problem(client.get(f"/cases/{uuid.uuid4()}"), 404)


def test_a_malformed_case_id_is_422(client: TestClient) -> None:
    assert_problem(client.get("/cases/nope"), 422)


# --- GET /cases ----------------------------------------------------------------------------


def test_an_unfiltered_list_returns_every_case_ordered_by_id(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    items = _walk(imported, 200)

    assert [i["id"] for i in items] == _case_ids(engine)
    assert set(items[0]) == CASE_KEYS


def test_filter_by_status(reconciled: dict[str, Any], imported: TestClient, engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE investigation.cases SET status = 'investigating'"
                " WHERE id IN (SELECT id FROM investigation.cases ORDER BY id LIMIT 5)"
            )
        )

    items = _walk(imported, 200, status="investigating")

    assert [i["id"] for i in items] == _case_ids(engine, "c.status = 'investigating'")
    assert len(items) == 5


def test_filter_by_discrepancy_type(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    items = _walk(imported, 200, discrepancy_type="fee_mismatch")

    assert [i["id"] for i in items] == _case_ids(engine, "d.type = 'fee_mismatch'")
    assert items


def test_filter_by_run(reconciled: dict[str, Any], imported: TestClient, engine: Engine) -> None:
    _open_cases_of_run(engine, second_run(engine, reconciled["id"]))

    items = _walk(imported, 200, run_id=reconciled["id"])

    assert [i["id"] for i in items] == _case_ids(engine, "d.run_id = :r", r=reconciled["id"])
    assert len(items) == 41


def test_filters_combine(reconciled: dict[str, Any], imported: TestClient, engine: Engine) -> None:
    _open_cases_of_run(engine, second_run(engine, reconciled["id"]))

    items = _walk(
        imported, 3, run_id=reconciled["id"], status="open", discrepancy_type="fee_mismatch"
    )

    assert [i["id"] for i in items] == _case_ids(
        engine,
        "d.run_id = :r AND c.status = 'open' AND d.type = 'fee_mismatch'",
        r=reconciled["id"],
    )
    assert items


def test_walking_pages_returns_each_case_once_while_cases_are_inserted(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    before = set(_case_ids(engine))
    first = imported.get("/cases", params={"limit": 7}).json()
    _open_cases_of_run(engine, second_run(engine, reconciled["id"]))

    rest: list[dict[str, Any]] = []
    cursor = first["next_cursor"]
    while cursor is not None:
        page = imported.get("/cases", params={"limit": 7, "cursor": cursor}).json()
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
        {"status": "closed"},
        {"discrepancy_type": "not_a_type"},
        {"run_id": "nope"},
        {"limit": 0},
        {"limit": 201},
    ],
)
def test_an_invalid_case_filter_is_422_with_field_errors(
    client: TestClient, params: dict[str, str | int]
) -> None:
    body = assert_problem(client.get("/cases", params=params), 422)

    assert body["errors"][0]["loc"][-1] == next(iter(params))


def test_a_malformed_case_cursor_is_422(client: TestClient) -> None:
    body = assert_problem(client.get("/cases", params={"cursor": "!!!"}), 422)

    assert "cursor" in body["detail"]


# --- PATCH /cases/{id} ---------------------------------------------------------------------


def test_an_update_at_the_current_version_changes_the_case_and_its_history(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    case = _a_case(imported)

    response = imported.patch(
        f"/cases/{case['id']}",
        json={"priority": "high", "assignee_id": "analyst-9"},
        headers={**USER, "If-Match": '"1"'},
    )

    assert response.status_code == 200
    assert response.headers["etag"] == '"2"'
    body = response.json()
    assert (body["priority"], body["assignee_id"], body["version"]) == ("high", "analyst-9", 2)
    assert {k: body[k] for k in ("id", "discrepancy_id", "status", "opened_at")} == {
        k: case[k] for k in ("id", "discrepancy_id", "status", "opened_at")
    }
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT priority, assignee_id, version FROM investigation.cases WHERE id = :c"),
            {"c": case["id"]},
        ).one()
    assert tuple(row) == ("high", "analyst-9", 2)
    history = imported.get(f"/cases/{case['id']}/history").json()["items"]
    assert history[-1]["event_type"] == "CaseUpdated"
    assert history[-1]["actor"] == {"type": "user", "id": "analyst-7"}
    assert history[-1]["payload"]["version"] == 2


def test_a_null_assignee_unassigns_and_an_omitted_field_is_kept(
    reconciled: dict[str, Any], imported: TestClient
) -> None:
    case = _a_case(imported)
    url = f"/cases/{case['id']}"
    imported.patch(url, json={"assignee_id": "analyst-9"}, headers={**USER, "If-Match": '"1"'})

    response = imported.patch(url, json={"assignee_id": None}, headers={**USER, "If-Match": '"2"'})

    assert response.status_code == 200
    assert (response.json()["assignee_id"], response.json()["priority"]) == (
        None,
        case["priority"],
    )


def test_an_update_with_a_stale_version_is_409_and_changes_nothing(
    reconciled: dict[str, Any], imported: TestClient, engine: Engine
) -> None:
    case = _a_case(imported)
    url = f"/cases/{case['id']}"
    assert (
        imported.patch(
            url, json={"priority": "high"}, headers={**USER, "If-Match": '"1"'}
        ).status_code
        == 200
    )
    events = _outbox_rows(engine)

    body = assert_problem(
        imported.patch(url, json={"priority": "low"}, headers={**USER, "If-Match": '"1"'}), 409
    )

    assert "version" in body["detail"]
    current = imported.get(url).json()
    assert (current["priority"], current["version"]) == ("high", 2)
    assert _outbox_rows(engine) == events


def test_an_update_without_if_match_is_428(
    reconciled: dict[str, Any], imported: TestClient
) -> None:
    case = _a_case(imported)

    body = assert_problem(
        imported.patch(f"/cases/{case['id']}", json={"priority": "high"}, headers=USER), 428
    )

    assert "If-Match" in body["detail"]


def test_an_update_without_x_actor_id_is_422(
    reconciled: dict[str, Any], imported: TestClient
) -> None:
    case = _a_case(imported)

    body = assert_problem(
        imported.patch(
            f"/cases/{case['id']}", json={"priority": "high"}, headers={"If-Match": '"1"'}
        ),
        422,
    )

    assert body["errors"][0]["loc"][-1] == "x-actor-id"


@pytest.mark.parametrize(
    ("json", "if_match"),
    [
        ({}, '"1"'),  # nothing to change
        ({"priority": "urgent"}, '"1"'),
        ({"assignee_id": ""}, '"1"'),
        ({"status": "resolved"}, '"1"'),  # D1: status transitions are not in this endpoint
        ({"priority": "high"}, '"one"'),
    ],
)
def test_an_invalid_update_is_422_and_changes_nothing(
    reconciled: dict[str, Any], imported: TestClient, json: dict[str, Any], if_match: str
) -> None:
    case = _a_case(imported)
    url = f"/cases/{case['id']}"

    assert_problem(imported.patch(url, json=json, headers={**USER, "If-Match": if_match}), 422)

    assert imported.get(url).json()["version"] == 1


def test_updating_an_unknown_case_is_404(client: TestClient) -> None:
    assert_problem(
        client.patch(
            f"/cases/{uuid.uuid4()}", json={"priority": "high"}, headers={**USER, "If-Match": '"1"'}
        ),
        404,
    )


# --- GET /cases/{id}/history ---------------------------------------------------------------


def test_the_history_is_the_case_audit_trail_in_order_with_actors(
    reconciled: dict[str, Any], imported: TestClient
) -> None:
    case = _a_case(imported)
    url = f"/cases/{case['id']}"
    imported.patch(url, json={"priority": "high"}, headers={**USER, "If-Match": '"1"'})

    history = imported.get(f"{url}/history").json()["items"]

    assert [(h["event_type"], h["actor"]) for h in history] == [
        ("CaseOpened", {"type": "system", "id": "open-case-on-discrepancy-detected"}),
        ("CaseUpdated", {"type": "user", "id": "analyst-7"}),
    ]
    assert history[0]["payload"]["discrepancy_id"] == case["discrepancy_id"]
    assert set(history[0]) == {"event_type", "event_version", "occurred_at", "actor", "payload"}


def test_the_history_of_an_unknown_case_is_404(client: TestClient) -> None:
    assert_problem(client.get(f"/cases/{uuid.uuid4()}/history"), 404)


@pytest.mark.parametrize(
    ("if_match", "status"),
    [
        ('W/"1"', 412),  # RFC 9110 13.1.1: If-Match compares strongly, a weak tag never matches
        ("*", 428),  # names no version
        ("+1", 422),
        ("1_0", 422),
        ('"1", "2"', 422),
    ],
)
def test_an_if_match_that_is_not_one_strong_version_changes_nothing(
    reconciled: dict[str, Any], imported: TestClient, if_match: str, status: int
) -> None:
    case = _a_case(imported)
    url = f"/cases/{case['id']}"

    response = imported.patch(
        url, json={"priority": "high"}, headers={**USER, "If-Match": if_match}
    )

    assert_problem(response, status)
    assert imported.get(url).json()["version"] == 1


def test_a_bare_version_in_if_match_is_accepted(
    reconciled: dict[str, Any], imported: TestClient
) -> None:
    case = _a_case(imported)

    response = imported.patch(
        f"/cases/{case['id']}", json={"priority": "high"}, headers={**USER, "If-Match": "1"}
    )

    assert response.status_code == 200
