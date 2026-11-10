import uuid
from dataclasses import dataclass
from typing import Protocol

from recon.investigation.domain.case import ReconciliationCase
from recon.shared_kernel.ports import UnitOfWork


@dataclass(frozen=True, slots=True)
class DiscrepancyView:
    """What Investigation needs of a Reconciliation discrepancy (anti-corruption layer)."""

    id: uuid.UUID
    severity: str


class DiscrepancyReader(Protocol):
    def get(self, discrepancy_id: uuid.UUID) -> DiscrepancyView | None: ...


class CaseRepository(Protocol):
    def find_by_discrepancy(self, discrepancy_id: uuid.UUID) -> ReconciliationCase | None: ...

    def add(self, case: ReconciliationCase) -> bool:
        """Insert the case; ``False`` when its discrepancy already has one (nothing written)."""
        ...


class InvestigationUnitOfWork(UnitOfWork, Protocol):
    @property
    def cases(self) -> CaseRepository: ...

    @property
    def discrepancies(self) -> DiscrepancyReader: ...
