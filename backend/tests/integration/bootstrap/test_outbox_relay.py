"""AC-2c.1 and AS4: events are dispatched in-process from every context's outbox, at least
once, and a DiscrepancyDetected opens the discrepancy's case."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from recon.bootstrap import cli as bootstrap_cli
from recon.bootstrap.cli import main, reconcile_main, reference_main
from recon.bootstrap.outbox import OutboxRelay, default_relay
from recon.shared_kernel.events import OutboxMessage

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
                    "INSERT INTO recon.outbox (event_type, event_version, payload, created_at,"
                    " actor_type, actor_id) VALUES ('Probe', 1, CAST(:p AS jsonb), now(),"
                    " 'system', 'test')"
                ),
                {"p": f'{{"n": {n}}}'},
            )
    seen: list[object] = []
    broken = {"n": 1}

    def handler(message: OutboxMessage) -> None:
        if message.payload["n"] == broken["n"]:
            raise RuntimeError("handler down")
        seen.append(message.payload["n"])

    relay = OutboxRelay(database, {"Probe": [handler]})

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


def test_a_database_error_while_dispatching_is_a_warning_and_keeps_the_exit_code(
    database: Engine,
    sample: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class DownRelay:
        def drain(self) -> None:
            raise OperationalError("SELECT", {}, Exception("connection lost"))

    monkeypatch.setattr(bootstrap_cli, "default_relay", lambda engine: DownRelay())

    assert main([str(sample)]) == 0

    assert "recon-import: warning: events not dispatched, retried by the next command" in (
        capsys.readouterr().err
    )


def _probe(engine: Engine, actor_id: str = "test") -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recon.outbox (event_type, event_version, payload, created_at,"
                " actor_type, actor_id) VALUES ('Probe', 1, '{}', now(), 'system', :a)"
            ),
            {"a": actor_id},
        )


def test_the_audit_records_an_event_whose_business_handler_keeps_failing(
    database: Engine, migrated_url: str
) -> None:
    _probe(database)
    audited: list[str] = []

    def failing(message: OutboxMessage) -> None:
        raise RuntimeError("case handler down")

    relay = OutboxRelay(
        database,
        {"Probe": [failing]},
        every=[lambda m: audited.append(m.event_type)],
    )

    [failure] = relay.drain().failed

    assert "case handler down" in failure.error
    assert audited == ["Probe"]  # audited before the business handler ran
    assert _count(database, "SELECT count(*) FROM recon.outbox WHERE published_at IS NULL") == 1


def test_a_row_whose_actor_is_invalid_is_a_failed_delivery_not_a_crash(
    database: Engine, migrated_url: str
) -> None:
    _probe(database, actor_id=" ")

    [failure] = OutboxRelay(database, {}).drain().failed

    assert "non-empty ID" in failure.error


def test_a_failed_delivery_after_a_command_is_a_warning_and_keeps_exit_0(
    database: Engine,
    sample: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failing(message: OutboxMessage) -> None:
        raise RuntimeError("handler down")

    monkeypatch.setattr(
        bootstrap_cli,
        "default_relay",
        lambda engine: OutboxRelay(engine, {"SourceConflictDetected": [failing]}),
    )
    with database.begin() as connection:  # one event to deliver, whatever the sample holds
        connection.execute(
            text(
                "INSERT INTO ingestion.outbox (event_type, event_version, payload, created_at,"
                " actor_type, actor_id) VALUES ('SourceConflictDetected', 1, '{}', now(),"
                " 'system', 'test')"
            )
        )

    assert main([str(sample)]) == 0

    warnings = [line for line in capsys.readouterr().err.splitlines() if "warning" in line]
    assert warnings and all(
        line.startswith("recon-import: warning: event ")
        and "(SourceConflictDetected) of ingestion.outbox not delivered, retried by the next"
        " command: RuntimeError('handler down')"
        in line
        for line in warnings
    )


def test_replacing_a_run_carries_its_cases_over_and_closes_the_one_not_found_again(
    database: Engine, sample: Path
) -> None:
    assert main([str(sample)]) == 0
    assert reference_main([str(REFERENCE_FILE)]) == 0
    assert reconcile_main(OCTOBER) == 0
    with database.begin() as connection:
        # a case someone worked on, and a discrepancy the replacing run will not find again
        worked = connection.execute(
            text(
                "UPDATE investigation.cases SET assignee_id = 'analyst-7', version = 2"
                " WHERE id = (SELECT min(id::text)::uuid FROM investigation.cases)"
                " RETURNING id, discrepancy_id"
            )
        ).one()
        gone = connection.execute(
            text(
                "UPDATE recon.discrepancies SET fingerprint = repeat('0', 64)"
                " WHERE id = (SELECT discrepancy_id FROM investigation.cases"
                " WHERE id <> :worked ORDER BY id LIMIT 1) RETURNING id"
            ),
            {"worked": worked.id},
        ).scalar_one()
        [old_run] = connection.execute(text("SELECT id FROM recon.reconciliation_runs")).scalars()

    assert reconcile_main([*OCTOBER, "--replace"]) == 0

    with database.connect() as connection:
        runs: dict[object, object] = dict(
            connection.execute(text("SELECT id, status FROM recon.reconciliation_runs")).all()
        )
        [new_run] = [run for run, status in runs.items() if run != old_run]
        assert runs == {old_run: "superseded", new_run: "completed"}
        old = connection.execute(
            text(
                "SELECT d.id, d.status, n.fingerprint = d.fingerprint FROM recon.discrepancies d"
                " LEFT JOIN recon.discrepancies n ON n.id = d.superseded_by"
                " WHERE d.run_id = :run"
            ),
            {"run": old_run},
        ).all()
        assert {status for _, status, _ in old} == {"superseded"}
        assert sorted(str(same) for i, _, same in old if i != gone) == ["True"] * 40
        assert [same for i, _, same in old if i == gone] == [None]  # no successor
        cases = connection.execute(
            text(
                "SELECT c.id, d.run_id, c.status, c.close_reason, c.assignee_id, c.version"
                " FROM investigation.cases c JOIN recon.discrepancies d ON d.id = c.discrepancy_id"
            )
        ).all()
        by_id = {c.id: c for c in cases}
        assert tuple(by_id[worked.id])[1:] == (new_run, "open", None, "analyst-7", 2)
        closed = [c for c in cases if c.run_id == old_run]
        assert [tuple(c)[2:4] for c in closed] == [("resolved", "superseded")]
        # 40 carried over; the discrepancy under its real fingerprint is new and gets a case
        assert sum(c.run_id == new_run for c in cases) == 41 and len(cases) == 42
        audited: dict[object, object] = dict(
            connection.execute(
                text(
                    "SELECT event_type, count(*) FROM audit.events WHERE event_type IN"
                    " ('DiscrepancySuperseded', 'CaseCarriedOver', 'CaseResolved', 'CaseOpened')"
                    " GROUP BY event_type"
                )
            ).all()
        )
        assert audited == {
            "DiscrepancySuperseded": 41,
            "CaseCarriedOver": 40,
            "CaseResolved": 1,
            "CaseOpened": 42,
        }
    for outbox in ("ingestion.outbox", "recon.outbox", "investigation.outbox"):
        assert _count(database, f"SELECT count(*) FROM {outbox} WHERE published_at IS NULL") == 0
