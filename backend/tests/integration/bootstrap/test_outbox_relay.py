"""AC-2c.1 and AS4: events are dispatched in-process from every context's outbox, at least
once, and a DiscrepancyDetected opens the discrepancy's case."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text

from recon.bootstrap.cli import main, reconcile_main, reference_main
from recon.bootstrap.outbox import OutboxRelay, default_relay

REFERENCE_FILE = Path(__file__).parents[3] / "reference" / "gateway-policy-2026.json"
OCTOBER = ["--from", "2026-10-01", "--to", "2026-10-31"]


def _count(engine: Engine, sql: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(sql)).scalar_one())


@pytest.fixture
def database(migrated_url: str, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv("RECON_DATABASE_URL", migrated_url)
    return engine


def test_reconciling_through_the_command_opens_exactly_one_case_per_discrepancy(
    database: Engine, sample: Path
) -> None:
    assert main([str(sample)]) == 0
    assert reference_main([str(REFERENCE_FILE)]) == 0
    assert reconcile_main(OCTOBER) == 0

    assert _count(database, "SELECT count(*) FROM recon.discrepancies") == 41
    assert (
        _count(
            database,
            "SELECT count(*) FROM recon.discrepancies d"
            " JOIN investigation.cases c ON c.discrepancy_id = d.id",
        )
        == 41
    )
    for outbox in ("ingestion.outbox", "recon.outbox", "investigation.outbox"):
        assert _count(database, f"SELECT count(*) FROM {outbox} WHERE published_at IS NULL") == 0
    assert _count(database, "SELECT count(*) FROM investigation.outbox") == 41

    # a second command delivers nothing again and opens no case
    assert reconcile_main(OCTOBER) == 0
    assert _count(database, "SELECT count(*) FROM investigation.cases") == 41
    assert _count(database, "SELECT count(*) FROM investigation.outbox") == 41


def test_a_failing_handler_leaves_its_event_unpublished_and_the_next_drain_retries_it(
    database: Engine, migrated_url: str
) -> None:
    with database.begin() as connection:
        for n in (1, 2):
            connection.execute(
                text(
                    "INSERT INTO recon.outbox (event_type, event_version, payload, created_at)"
                    " VALUES ('Probe', 1, CAST(:p AS jsonb), now())"
                ),
                {"p": f'{{"n": {n}}}'},
            )
    seen: list[object] = []
    broken = {"n": 1}

    def handler(payload: dict[str, object]) -> None:
        if payload["n"] == broken["n"]:
            raise RuntimeError("handler down")
        seen.append(payload["n"])

    relay = OutboxRelay(create_engine(migrated_url), {"Probe": [handler]})

    first = relay.drain()

    [failure] = first.failed
    assert (first.delivered, failure.outbox, failure.event_type) == (1, "recon.outbox", "Probe")
    assert "handler down" in failure.error
    assert seen == [2]
    broken["n"] = 0
    assert relay.drain().delivered == 1
    assert seen == [2, 1]
    assert _count(database, "SELECT count(*) FROM recon.outbox WHERE published_at IS NULL") == 0


def test_the_default_relay_routes_discrepancy_detected_to_open_case(database: Engine) -> None:
    relay = default_relay(database)

    assert "DiscrepancyDetected" in relay.event_types
