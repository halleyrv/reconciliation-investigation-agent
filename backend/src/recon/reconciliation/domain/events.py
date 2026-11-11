import uuid
from dataclasses import dataclass
from typing import ClassVar

from recon.shared_kernel.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class DiscrepancyDetected(DomainEvent):
    aggregate: ClassVar[tuple[str, str]] = ("Discrepancy", "discrepancy_id")
    discrepancy_id: uuid.UUID
    type: str
    delta_minor: int
    currency: str
