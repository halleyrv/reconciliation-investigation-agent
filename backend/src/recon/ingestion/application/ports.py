from typing import Protocol

from recon.ingestion.domain.batch import ImportBatch
from recon.ingestion.domain.records import RawRecord, RecordType, SourceConflict, SourceRecord
from recon.shared_kernel.ports import UnitOfWork


class ImportBatchRepository(Protocol):
    def get_by_file(self, source: str, file_sha256: str) -> ImportBatch | None: ...

    def add(self, batch: ImportBatch) -> None: ...

    def save(self, batch: ImportBatch) -> None: ...


class SourceRecordRepository(Protocol):
    def add_raw(self, raw: RawRecord) -> None: ...

    def add(self, record: SourceRecord, raw: RawRecord) -> None: ...

    def find_canonical_raw(
        self, source: str, record_type: RecordType, external_id: str
    ) -> RawRecord | None:
        """The raw record the canonical row with this external ID was parsed from."""
        ...

    def add_conflict(self, conflict: SourceConflict) -> None: ...


class IngestionUnitOfWork(UnitOfWork, Protocol):
    batches: ImportBatchRepository
    records: SourceRecordRepository
