import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

from recon.ingestion.adapters.outbound.simulator_files import read_export
from recon.ingestion.adapters.outbound.sql import SqlAlchemyIngestionUnitOfWork
from recon.ingestion.application.import_export import ImportExport, ManifestMismatch
from recon.ingestion.domain.records import RecordType
from recon.shared_kernel.ports import SystemClock, UuidIdGenerator

AMOUNT_COLUMN = {
    RecordType.SETTLEMENTS: "net_amount_minor",
    RecordType.AUTHORIZATIONS: "max_amount_minor",
}
AMOUNT_FIELD = {
    RecordType.ORDERS: "total_amount",
    RecordType.SETTLEMENTS: "net_amount",
    RecordType.AUTHORIZATIONS: "max_amount",
}


def _import(engine: Engine, export_dir: Path) -> ImportExport:
    uow = SqlAlchemyIngestionUnitOfWork(sessionmaker(engine))
    return ImportExport(uow, SystemClock(), UuidIdGenerator())


def _scalar(engine: Engine, sql: str, **params: object) -> object:
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar_one()


def _rewrite(export_dir: Path, name: str, records: list[dict[str, object]]) -> None:
    path = export_dir / name
    data = json.loads(path.read_text())
    data["records"] = records
    path.write_text(json.dumps(data, indent=2) + "\n")
    manifest_path = export_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def test_importing_the_sample_loads_every_record_into_postgres(
    engine: Engine, sample: Path
) -> None:
    batches = _import(engine, sample)(read_export(sample))

    assert all(b.status == "completed" for b in batches)
    for record_type in RecordType:
        records = json.loads((sample / f"{record_type.value}.json").read_text())["records"]
        id_field = next(iter(records[0]))
        first_seen = {r[id_field]: r for r in reversed(records)}
        field = AMOUNT_FIELD.get(record_type, "amount")
        table = f"ingestion.{record_type.value}"
        column = AMOUNT_COLUMN.get(record_type, "amount_minor")
        batch = next(b for b in batches if b.record_type == record_type)

        raw = _scalar(
            engine, "SELECT count(*) FROM ingestion.raw_records WHERE batch_id = :b", b=batch.id
        )
        assert raw == len(records)
        assert _scalar(engine, f"SELECT count(*) FROM {table}") == len(first_seen)
        expected = sum(Decimal(str(r[field])) for r in first_seen.values()) * 100
        assert _scalar(engine, f"SELECT sum({column}) FROM {table}") == expected
    assert _scalar(engine, "SELECT count(*) FROM ingestion.source_conflicts") == 4
    stored_at = _scalar(
        engine, "SELECT placed_at FROM ingestion.orders WHERE external_id = 'ORD-000001'"
    )
    assert str(stored_at) == "2026-10-01 03:46:51+00:00"


def test_reimporting_the_sample_returns_the_same_batches_and_adds_no_rows(
    engine: Engine, sample: Path
) -> None:
    first = _import(engine, sample)(read_export(sample))
    counts = (
        "SELECT (SELECT count(*) FROM ingestion.raw_records),"
        " (SELECT count(*) FROM ingestion.outbox)"
    )
    with engine.connect() as connection:
        before = connection.execute(text(counts)).one()

    second = _import(engine, sample)(read_export(sample))

    assert [b.id for b in second] == [b.id for b in first]
    assert [b.status for b in second] == [b.status for b in first]
    with engine.connect() as connection:
        assert connection.execute(text(counts)).one() == before


def test_a_conflicting_resend_is_recorded_with_its_event_and_leaves_the_order_unchanged(
    engine: Engine, sample: Path
) -> None:
    orders = json.loads((sample / "orders.json").read_text())["records"]
    first, resent = (r for r in orders if r["order_id"] == "ORD-000180")

    _import(engine, sample)(read_export(sample))

    with engine.connect() as connection:
        conflict = connection.execute(
            text(
                "SELECT e.line_no, i.line_no, i.payload->>'customer_email'"
                " FROM ingestion.source_conflicts c"
                " JOIN ingestion.raw_records e ON e.id = c.existing_raw_record_id"
                " JOIN ingestion.raw_records i ON i.id = c.incoming_raw_record_id"
                " WHERE c.external_id = 'ORD-000180'"
            )
        ).one()
        email = connection.execute(
            text("SELECT customer_email FROM ingestion.orders WHERE external_id = 'ORD-000180'")
        ).scalar_one()
        events = (
            connection.execute(
                text(
                    "SELECT payload->>'external_id' FROM ingestion.outbox"
                    " WHERE event_type = 'SourceConflictDetected' AND event_version = 1"
                )
            )
            .scalars()
            .all()
        )
    assert conflict[0] < conflict[1]
    assert conflict[2] == resent["customer_email"]
    assert email == first["customer_email"]
    assert sorted(events) == ["ORD-000026", "ORD-000080", "ORD-000101", "ORD-000180"]


def test_an_invalid_row_persists_a_failed_batch_with_its_error_and_no_records(
    engine: Engine, sample: Path
) -> None:
    payments = json.loads((sample / "payments.json").read_text())["records"]
    payments[16]["amount"] = 12.5
    _rewrite(sample, "payments.json", payments)

    batches = _import(engine, sample)(read_export(sample))

    batch = next(b for b in batches if b.record_type == RecordType.PAYMENTS)
    with engine.connect() as connection:
        status = connection.execute(
            text("SELECT status FROM ingestion.import_batches WHERE id = :id"), {"id": batch.id}
        ).scalar_one()
        errors = connection.execute(
            text(
                "SELECT b.file_name, e.line_no, e.field FROM ingestion.import_batch_errors e"
                " JOIN ingestion.import_batches b ON b.id = e.batch_id WHERE e.batch_id = :id"
            ),
            {"id": batch.id},
        ).all()
    assert status == "failed"
    assert [tuple(e) for e in errors] == [("payments.json", 17, "amount")]
    assert _scalar(engine, "SELECT count(*) FROM ingestion.payments") == 0
    assert (
        _scalar(
            engine, "SELECT count(*) FROM ingestion.raw_records WHERE batch_id = :b", b=batch.id
        )
        == 0
    )
    assert _import(engine, sample)(read_export(sample))[1].errors == batch.errors


def test_a_manifest_mismatch_writes_nothing(engine: Engine, sample: Path) -> None:
    path = sample / "fees.json"
    path.write_text(path.read_text().replace("12.33", "12.34", 1))

    with pytest.raises(ManifestMismatch):
        _import(engine, sample)(read_export(sample))

    assert _scalar(engine, "SELECT count(*) FROM ingestion.import_batches") == 0


def test_a_failure_halfway_through_a_file_leaves_no_rows_of_that_file(
    engine: Engine, sample: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import_export = _import(engine, sample)
    from recon.ingestion.adapters.outbound import sql

    original = sql.SqlAlchemySourceRecords.add
    calls = {"n": 0}

    def flaky_add(self: sql.SqlAlchemySourceRecords, record: object, raw: object) -> None:
        calls["n"] += 1
        if calls["n"] == 300:  # inside payments.json, after every order
            raise RuntimeError("connection lost")
        original(self, record, raw)  # type: ignore[arg-type]

    monkeypatch.setattr(sql.SqlAlchemySourceRecords, "add", flaky_add)

    with pytest.raises(RuntimeError, match="connection lost"):
        import_export(read_export(sample))

    assert _scalar(engine, "SELECT count(*) FROM ingestion.orders") == 200
    assert _scalar(engine, "SELECT count(*) FROM ingestion.payments") == 0
    assert _scalar(engine, "SELECT count(*) FROM ingestion.import_batches") == 1


def test_instants_are_stored_as_utc_whatever_the_session_time_zone(
    engine: Engine, migrated_url: str, sample: Path
) -> None:
    lima = create_engine(migrated_url, connect_args={"options": "-c timezone=America/Lima"})
    try:
        ImportExport(
            SqlAlchemyIngestionUnitOfWork(sessionmaker(lima)), SystemClock(), UuidIdGenerator()
        )(read_export(sample))
    finally:
        lima.dispose()

    utc = _scalar(
        engine,
        "SELECT to_char(placed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS')"
        " FROM ingestion.orders WHERE external_id = 'ORD-000001'",
    )
    assert utc == "2026-10-01T03:46:51"
