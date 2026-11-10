import uuid
from dataclasses import dataclass

from recon.shared_kernel.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class DiscrepancyDetected(DomainEvent):
    discrepancy_id: uuid.UUID
    type: str
    delta_minor: int
    currency: str
