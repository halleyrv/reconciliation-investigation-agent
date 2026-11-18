import uuid
from dataclasses import dataclass
from typing import ClassVar

from recon.ingestion.domain.records import RecordType
from recon.shared_kernel.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class SourceConflictDetected(DomainEvent):
    aggregate: ClassVar[tuple[str, str]] = ("SourceConflict", "conflict_id")
    conflict_id: uuid.UUID
    source: str
    record_type: RecordType
    external_id: str
    existing_raw_record_id: uuid.UUID
    incoming_raw_record_id: uuid.UUID
