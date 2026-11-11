import uuid
from dataclasses import dataclass
from typing import ClassVar

from recon.shared_kernel.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class CaseOpened(DomainEvent):
    aggregate: ClassVar[tuple[str, str]] = ("ReconciliationCase", "case_id")
    case_id: uuid.UUID
    discrepancy_id: uuid.UUID
    priority: str
