"""AC-2c.6: every Phase 2 domain event appears in audit.events with its actor, the hash chain
verifies, and the database rejects UPDATE and DELETE on audit.events."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from recon.audit.adapters.outbound.sql import SqlAlchemyAuditUnitOfWork
from recon.audit.application.record_event import RecordEvent, VerifyChain
from recon.audit.domain.chain import AuditRecord
from recon.bootstrap.cli import main, reconcile_main, reference_main
from recon.bootstrap.outbox import default_relay
from recon.shared_kernel.actor import Actor

REFERENCE_FILE = Path(__file__).parents[3] / "reference" / "gateway-policy-2026.json"
OCTOBER = ["--from", "2026-10-01", "--to", "2026-10-31"]
OUTBOX_ROWS = " UNION ALL ".join(
    f"SELECT '{o}' AS source, id, event_type, actor_type, actor_id, aggregate_type, aggregate_id"
    f" FROM {o}"
    for o in ("ingestion.outbox", "recon.outbox", "investigation.outbox")
)


def _rows(engine: Engine, sql: str) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [tuple(r) for r in connection.execute(text(sql))]


def _verify(engine: Engine) -> tuple[int, int | None]:
    report = VerifyChain(SqlAlchemyAuditUnitOfWork(sessionmaker(engine)))()
    return report.entries, report.first_broken


@pytest.fixture
def audited(
    migrated_url: str, engine: Engine, sample: Path, monkeypatch: pytest.MonkeyPatch
) -> Engine:
    monkeypatch.setenv("RECON_DATABASE_URL", migrated_url)
    assert main([str(sample)]) == 0
    assert reference_main([str(REFERENCE_FILE)]) == 0
    assert reconcile_main(OCTOBER) == 0
    return engine


def test_every_event_is_audited_once_with_its_actor_and_aggregate(audited: Engine) -> None:
    outbox = sorted(_rows(audited, OUTBOX_ROWS), key=str)
    audit = sorted(
        _rows(
            audited,
            "SELECT source, source_event_id, event_type, actor_type, actor_id, aggregate_type,"
            " aggregate_id FROM audit.events",
        ),
        key=str,
    )

    assert audit == outbox
    actors = {(r[2], r[3], r[4], r[5]) for r in audit}
    assert {
        ("DiscrepancyDetected", "system", "recon-reconcile", "Discrepancy"),
        ("CaseOpened", "system", "open-case-on-discrepancy-detected", "ReconciliationCase"),
    } <= actors
    assert all(r[6] is not None for r in audit)
    assert _rows(
        audited,
        "SELECT count(*) FROM audit.events a JOIN recon.discrepancies d ON d.id = a.aggregate_id"
        " WHERE a.event_type = 'DiscrepancyDetected'",
    ) == [(41,)]
    assert _verify(audited) == (len(outbox), None)


def test_redelivering_every_event_audits_nothing_twice(audited: Engine) -> None:
    before = _rows(audited, "SELECT count(*) FROM audit.events")
    with audited.begin() as connection:
        for o in ("ingestion.outbox", "recon.outbox", "investigation.outbox"):
            connection.execute(text(f"UPDATE {o} SET published_at = NULL"))

    assert default_relay(audited).drain().failed == []

    assert _rows(audited, "SELECT count(*) FROM audit.events") == before
    assert _verify(audited)[1] is None


@pytest.mark.parametrize(
    "change",
    ["UPDATE audit.events SET actor_id = 'someone else'", "DELETE FROM audit.events"],
)
def test_the_database_rejects_changing_audit_events(audited: Engine, change: str) -> None:
    with pytest.raises(DBAPIError, match="append-only"), audited.begin() as connection:
        connection.execute(text(change))


def test_verification_finds_an_entry_changed_behind_the_trigger(audited: Engine) -> None:
    [(victim,)] = _rows(audited, "SELECT id FROM audit.events ORDER BY id OFFSET 5 LIMIT 1")
    with audited.begin() as connection:
        connection.execute(text("ALTER TABLE audit.events DISABLE TRIGGER USER"))
        connection.execute(
            text("UPDATE audit.events SET payload = '{}' WHERE id = :id"), {"id": victim}
        )
        connection.execute(text("ALTER TABLE audit.events ENABLE TRIGGER USER"))

    assert _verify(audited)[1] == victim


def test_concurrent_recording_keeps_one_linear_chain(engine: Engine) -> None:
    barrier = threading.Barrier(8)

    def record(n: int) -> bool:
        barrier.wait(timeout=10)
        return RecordEvent(SqlAlchemyAuditUnitOfWork(sessionmaker(engine)))(
            AuditRecord(
                source="recon.outbox",
                source_event_id=n,
                occurred_at=datetime(2026, 11, 10, tzinfo=UTC),
                actor=Actor.system("test"),
                aggregate_type=None,
                aggregate_id=None,
                event_type="Probe",
                event_version=1,
                payload={"n": n},
            )
        )

    with ThreadPoolExecutor(8) as pool:
        assert all(pool.map(record, range(1, 9)))

    assert not barrier.broken
    assert _verify(engine) == (8, None)
    [(links,)] = _rows(engine, "SELECT count(DISTINCT prev_sha256) FROM audit.events")
    assert links == 7  # every entry but the first links a different predecessor
