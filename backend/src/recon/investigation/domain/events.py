import uuid
from dataclasses import dataclass

from recon.shared_kernel.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class CaseOpened(DomainEvent):
    case_id: uuid.UUID
    discrepancy_id: uuid.UUID
    priority: str
