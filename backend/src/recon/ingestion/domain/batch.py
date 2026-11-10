import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from recon.ingestion.domain.records import RecordType

type BatchStatus = Literal["pending", "processing", "completed", "failed"]


class InvalidBatchTransition(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RowError:
    """Why a file was rejected. ``line_no`` is the 1-based record position; 0 means the file."""

    file_name: str
    line_no: int
    field: str
    message: str


@dataclass(slots=True)
class ImportBatch:
    """One file imported from one source. A completed batch is immutable."""

    id: uuid.UUID
    source: str
    record_type: RecordType
    file_name: str
    file_sha256: str
    status: BatchStatus
    started_at: datetime
    row_count: int = 0
    errors: tuple[RowError, ...] = ()
    finished_at: datetime | None = None

    @classmethod
    def start(
        cls,
        batch_id: uuid.UUID,
        source: str,
        record_type: RecordType,
        file_name: str,
        file_sha256: str,
        at: datetime,
    ) -> ImportBatch:
        return cls(batch_id, source, record_type, file_name, file_sha256, "processing", at)

    def complete(self, row_count: int, at: datetime) -> None:
        self._finish("completed", at)
        self.row_count = row_count

    def fail(self, errors: tuple[RowError, ...], at: datetime) -> None:
        if not errors:
            raise ValueError("a failed batch must say why")
        self._finish("failed", at)
        self.errors = errors

    def _finish(self, status: BatchStatus, at: datetime) -> None:
        if self.status != "processing":
            raise InvalidBatchTransition(
                f"batch {self.id} is {self.status}, cannot become {status}"
            )
        self.status = status
        self.finished_at = at
