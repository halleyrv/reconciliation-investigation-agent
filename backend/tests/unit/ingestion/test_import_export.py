import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from recon.ingestion.adapters.outbound.memory import InMemoryIngestionUnitOfWork
from recon.ingestion.adapters.outbound.simulator_files import read_export
from recon.ingestion.application.import_export import ImportExport, ManifestMismatch
from recon.ingestion.domain.events import SourceConflictDetected
from recon.ingestion.domain.records import (
    Authorization,
    Order,
    RecordType,
    Settlement,
    SourceRecord,
)

FILES = {t: f"{t.value}.json" for t in RecordType}


def _amount_minor(record: SourceRecord) -> int:
    match record:
        case Order():
            return record.total.amount_minor
        case Settlement():
            return record.net_amount.amount_minor
        case Authorization():
            return record.max_amount.amount_minor
        case _:
            return record.amount.amount_minor


def _records(export_dir: Path, record_type: RecordType) -> list[dict[str, str]]:
    data = json.loads((export_dir / FILES[record_type]).read_text())
    records: list[dict[str, str]] = data["records"]
    return records


def _editable(export_dir: Path, record_type: RecordType) -> list[dict[str, object]]:
    records: list[dict[str, object]] = json.loads((export_dir / FILES[record_type]).read_text())[
        "records"
    ]
    return records


def _rewrite(export_dir: Path, name: str, records: list[dict[str, object]]) -> None:
    """Write a tampered file and update the manifest, as a well-behaved sender would."""
    path = export_dir / name
    data = json.loads(path.read_text())
    data["records"] = records
    path.write_text(json.dumps(data, indent=2) + "\n")
    manifest_path = export_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def test_importing_the_sample_loads_every_record_with_exact_amounts(
    sample: Path, uow: InMemoryIngestionUnitOfWork, import_export: ImportExport
) -> None:
    batches = import_export(read_export(sample))

    assert {b.file_name for b in batches} == set(FILES.values())
    assert all(b.status == "completed" for b in batches)
    for record_type, name in FILES.items():
        file_records = _records(sample, record_type)
        first_seen = {next(iter(r.values())): r for r in reversed(file_records)}
        canonical = uow.records_of(record_type)
        batch = next(b for b in batches if b.file_name == name)

        assert batch.row_count == len(file_records)
        assert uow.raw_count(batch.id) == len(file_records)
        assert len(canonical) == len(first_seen)
        amount_field = next(k for k in file_records[0] if "amount" in k)
        expected_sum = sum(Decimal(r[amount_field]) for r in first_seen.values()) * 100
        assert sum(_amount_minor(r) for r in canonical) == expected_sum
    first_order = uow.records_of(RecordType.ORDERS)[0]
    assert isinstance(first_order, Order)
    assert first_order.placed_at == datetime(2026, 10, 1, 3, 46, 51, tzinfo=UTC)


def test_reimporting_the_same_files_returns_the_existing_batches_and_writes_nothing(
    sample: Path, uow: InMemoryIngestionUnitOfWork, import_export: ImportExport
) -> None:
    first = import_export(read_export(sample))
    rows_before, events_before = uow.total_rows(), list(uow.outbox)

    second = import_export(read_export(sample))

    assert [b.id for b in second] == [b.id for b in first]
    assert uow.total_rows() == rows_before
    assert uow.outbox == events_before


def test_a_resent_record_with_a_different_payload_is_a_conflict_not_an_update(
    sample: Path, uow: InMemoryIngestionUnitOfWork, import_export: ImportExport
) -> None:
    orders = _records(sample, RecordType.ORDERS)
    resent = [i for i, r in enumerate(orders) if r["order_id"] == "ORD-000180"]
    assert len(resent) == 2, "the sample re-sends ORD-000180 (ANM-0031)"

    import_export(read_export(sample))

    conflicts = [e for e in uow.outbox if isinstance(e, SourceConflictDetected)]
    assert Counter(e.external_id for e in conflicts) == Counter(
        {"ORD-000026": 1, "ORD-000080": 1, "ORD-000101": 1, "ORD-000180": 1}
    )
    assert len(uow.conflicts) == 4
    conflict = next(c for c in uow.conflicts if c.external_id == "ORD-000180")
    assert uow.raw(conflict.existing_raw_record_id).line_no == resent[0] + 1
    assert uow.raw(conflict.incoming_raw_record_id).line_no == resent[1] + 1
    stored = next(o for o in uow.records_of(RecordType.ORDERS) if o.external_id == "ORD-000180")
    assert isinstance(stored, Order)
    assert stored.customer_email == orders[resent[0]]["customer_email"]
    assert stored.customer_email != orders[resent[1]]["customer_email"]


def test_a_resent_record_with_an_identical_payload_is_a_no_op(
    sample: Path, uow: InMemoryIngestionUnitOfWork, import_export: ImportExport
) -> None:
    payments = _editable(sample, RecordType.PAYMENTS)
    _rewrite(sample, "payments.json", [*payments, dict(payments[0])])

    batches = import_export(read_export(sample))

    batch = next(b for b in batches if b.file_name == "payments.json")
    assert batch.status == "completed"
    assert len(uow.records_of(RecordType.PAYMENTS)) == len(payments)
    assert not [c for c in uow.conflicts if c.external_id == payments[0]["payment_id"]]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("amount", 12.5, "JSON float amount"),
        ("amount", "12.505", "more than 2 decimals"),
        ("captured_at", "yesterday", "schema violation"),
        ("unexpected", "x", "schema violation: unknown field"),
    ],
)
def test_one_invalid_row_fails_the_whole_batch_and_names_file_line_and_field(
    sample: Path,
    uow: InMemoryIngestionUnitOfWork,
    import_export: ImportExport,
    field: str,
    value: object,
    reason: str,
) -> None:
    payments = _editable(sample, RecordType.PAYMENTS)
    payments[16] = {**payments[16], field: value}
    _rewrite(sample, "payments.json", payments)

    batches = import_export(read_export(sample))

    batch = next(b for b in batches if b.file_name == "payments.json")
    assert batch.status == "failed", reason
    assert uow.records_of(RecordType.PAYMENTS) == []
    assert uow.raw_count(batch.id) == 0
    assert [(e.file_name, e.line_no, e.field) for e in batch.errors] == [
        ("payments.json", 17, field)
    ]
    others = [b for b in batches if b.file_name != "payments.json"]
    assert all(b.status == "completed" for b in others)


def test_a_missing_required_field_is_reported_by_name(
    sample: Path, import_export: ImportExport
) -> None:
    refunds = _editable(sample, RecordType.REFUNDS)
    del refunds[0]["refunded_at"]
    _rewrite(sample, "refunds.json", refunds)

    batches = import_export(read_export(sample))

    batch = next(b for b in batches if b.file_name == "refunds.json")
    assert [(e.line_no, e.field) for e in batch.errors] == [(1, "refunded_at")]


def test_a_file_whose_hash_differs_from_the_manifest_is_rejected_before_any_write(
    sample: Path, uow: InMemoryIngestionUnitOfWork, import_export: ImportExport
) -> None:
    path = sample / "fees.json"
    path.write_text(path.read_text().replace("12.33", "12.34", 1))

    with pytest.raises(ManifestMismatch, match=r"fees\.json"):
        import_export(read_export(sample))

    assert uow.total_rows() == 0
    assert uow.stored_batches() == []
