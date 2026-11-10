"""In-memory Ingestion persistence for unit tests. It keeps the same transaction and uniqueness
rules as PostgreSQL, so a test that passes here cannot rely on a skipped rule."""

import copy
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

from recon.ingestion.domain.batch import ImportBatch
from recon.ingestion.domain.records import (
    Authorization,
    BankTransaction,
    Fee,
    Order,
    Payment,
    RawRecord,
    RecordType,
    Refund,
    Settlement,
    SourceConflict,
    SourceRecord,
)
from recon.shared_kernel.events import DomainEvent

_TYPE_OF: dict[type, RecordType] = {
    Order: RecordType.ORDERS,
    Payment: RecordType.PAYMENTS,
    Refund: RecordType.REFUNDS,
    Fee: RecordType.FEES,
    Settlement: RecordType.SETTLEMENTS,
    BankTransaction: RecordType.BANK_TRANSACTIONS,
    Authorization: RecordType.AUTHORIZATIONS,
}


class UniqueViolation(Exception):
    pass


@dataclass
class _State:
    batches: dict[uuid.UUID, ImportBatch] = field(default_factory=dict)
    raws: dict[uuid.UUID, RawRecord] = field(default_factory=dict)
    records: dict[tuple[str, RecordType, str], tuple[SourceRecord, uuid.UUID]] = field(
        default_factory=dict
    )
    conflicts: list[SourceConflict] = field(default_factory=list)
    outbox: list[DomainEvent] = field(default_factory=list)


class _Batches:
    def __init__(self, uow: InMemoryIngestionUnitOfWork) -> None:
        self._uow = uow

    def get_by_file(self, source: str, file_sha256: str) -> ImportBatch | None:
        for batch in self._uow.state.batches.values():
            if (batch.source, batch.file_sha256) == (source, file_sha256):
                return copy.deepcopy(batch)
        return None

    def add(self, batch: ImportBatch) -> None:
        if self.get_by_file(batch.source, batch.file_sha256) is not None:
            raise UniqueViolation(f"file {batch.file_sha256} already imported for {batch.source}")
        self._uow.state.batches[batch.id] = copy.deepcopy(batch)

    def save(self, batch: ImportBatch) -> None:
        self._uow.state.batches[batch.id] = copy.deepcopy(batch)


class _Records:
    def __init__(self, uow: InMemoryIngestionUnitOfWork) -> None:
        self._uow = uow

    def add_raw(self, raw: RawRecord) -> None:
        self._uow.state.raws[raw.id] = raw

    def add(self, record: SourceRecord, raw: RawRecord) -> None:
        key = (raw.source, _TYPE_OF[type(record)], record.external_id)
        if key in self._uow.state.records:
            raise UniqueViolation(f"duplicate {key}")
        self._uow.state.records[key] = (record, raw.id)

    def find_canonical_raws(
        self, source: str, record_type: RecordType, external_ids: Collection[str]
    ) -> dict[str, RawRecord]:
        records = self._uow.state.records
        return {
            external_id: self._uow.state.raws[records[key][1]]
            for external_id in external_ids
            if (key := (source, record_type, external_id)) in records
        }

    def add_conflict(self, conflict: SourceConflict) -> None:
        self._uow.state.conflicts.append(conflict)


class InMemoryIngestionUnitOfWork:
    def __init__(self) -> None:
        self.state = _State()
        self._committed = copy.deepcopy(self.state)
        self.batches = _Batches(self)
        self.records = _Records(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.state = copy.deepcopy(self._committed)

    def commit(self) -> None:
        self._committed = copy.deepcopy(self.state)

    def add_event(self, event: DomainEvent) -> None:
        self.state.outbox.append(event)

    # Inspection helpers for tests (committed state only).

    def records_of(self, record_type: RecordType) -> list[SourceRecord]:
        return [r for (_, t, _), (r, _) in self._committed.records.items() if t == record_type]

    def raw(self, raw_id: uuid.UUID) -> RawRecord:
        return self._committed.raws[raw_id]

    def raw_count(self, batch_id: uuid.UUID) -> int:
        return sum(1 for r in self._committed.raws.values() if r.batch_id == batch_id)

    def stored_batches(self) -> list[ImportBatch]:
        return list(self._committed.batches.values())

    def total_rows(self) -> int:
        c = self._committed
        return len(c.batches) + len(c.raws) + len(c.records) + len(c.conflicts) + len(c.outbox)

    @property
    def conflicts(self) -> list[SourceConflict]:
        return list(self._committed.conflicts)

    @property
    def outbox(self) -> list[DomainEvent]:
        return list(self._committed.outbox)
