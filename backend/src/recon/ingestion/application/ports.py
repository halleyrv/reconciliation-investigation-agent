from collections.abc import Collection
from typing import Protocol

from recon.ingestion.domain.batch import ImportBatch
from recon.ingestion.domain.records import RawRecord, RecordType, SourceConflict, SourceRecord
from recon.shared_kernel.ports import UnitOfWork


class ImportBatchRepository(Protocol):
    def lock_source(self, source: str) -> None:
        """Serialize imports of one source until the current transaction ends."""
        ...

    def get_by_file(self, source: str, file_sha256: str) -> ImportBatch | None: ...

    def add(self, batch: ImportBatch) -> None: ...

    def save(self, batch: ImportBatch) -> None: ...


class SourceRecordRepository(Protocol):
    def add_raw(self, raw: RawRecord) -> None: ...

    def add(self, record: SourceRecord, raw: RawRecord) -> None: ...

    def find_canonical_raws(
        self, source: str, record_type: RecordType, external_ids: Collection[str]
    ) -> dict[str, RawRecord]:
        """For each external ID that already has a canonical row: the raw record it came from."""
        ...

    def add_conflict(self, conflict: SourceConflict) -> None: ...


class IngestionUnitOfWork(UnitOfWork, Protocol):
    @property
    def batches(self) -> ImportBatchRepository: ...

    @property
    def records(self) -> SourceRecordRepository: ...
