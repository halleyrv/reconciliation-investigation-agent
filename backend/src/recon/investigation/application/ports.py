import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from recon.investigation.domain.case import CaseStatus, ReconciliationCase
from recon.shared_kernel.actor import Actor
from recon.shared_kernel.ports import UnitOfWork


@dataclass(frozen=True, slots=True)
class DiscrepancyView:
    """What Investigation needs of a Reconciliation discrepancy (anti-corruption layer)."""

    id: uuid.UUID
    severity: str
    superseded: bool = False
    superseded_by: uuid.UUID | None = None  # the one a replacing run found again


class DiscrepancyReader(Protocol):
    def lock_for_case(self, discrepancy_id: uuid.UUID) -> DiscrepancyView | None:
        """Read the discrepancy and hold it until the transaction ends, so a replacement
        cannot supersede it while its case is being opened."""
        ...

    def predecessor(self, discrepancy_id: uuid.UUID) -> uuid.UUID | None:
        """The discrepancy of the replaced run this one was found again for, if any."""
        ...


class CaseRepository(Protocol):
    def find_by_discrepancy(self, discrepancy_id: uuid.UUID) -> ReconciliationCase | None: ...

    def get(self, case_id: uuid.UUID) -> ReconciliationCase | None: ...

    def add(self, case: ReconciliationCase) -> bool:
        """Insert the case; ``False`` when its discrepancy already has one (nothing written)."""
        ...

    def update(self, case: ReconciliationCase, expected_version: int) -> bool:
        """Store the case if the stored one is still at ``expected_version``; ``False`` (nothing
        written) when another writer changed it first. Writes the priority, assignee and
        version only."""
        ...

    def carry_over(self, case: ReconciliationCase, from_discrepancy_id: uuid.UUID) -> bool:
        """Move the case to ``case.discrepancy_id`` if it is still on ``from_discrepancy_id``;
        ``False`` (nothing written) when a concurrent carry-over moved it first."""
        ...

    def close(self, case: ReconciliationCase, expected_version: int) -> bool:
        """Store the case's close if the stored one is still at ``expected_version``."""
        ...


class InvestigationUnitOfWork(UnitOfWork, Protocol):
    @property
    def cases(self) -> CaseRepository: ...

    @property
    def discrepancies(self) -> DiscrepancyReader: ...


@dataclass(frozen=True, slots=True)
class CaseFilter:
    status: CaseStatus | None = None
    discrepancy_type: str | None = None
    run_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class DiscrepancySnapshot:
    """A case's discrepancy as the API shows it, read from Reconciliation's tables."""

    id: uuid.UUID
    run_id: uuid.UUID
    type: str
    severity: str
    expected_minor: int
    actual_minor: int
    delta_minor: int
    currency: str
    status: str
    detected_at: datetime


@dataclass(frozen=True, slots=True)
class RecordRef:
    type: str  # the source record table: order, payment, refund, fee, settlement, ...
    id: uuid.UUID


@dataclass(frozen=True, slots=True)
class CaseDetail:
    case: ReconciliationCase
    discrepancy: DiscrepancySnapshot
    records: list[RecordRef]


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    event_type: str
    event_version: int
    occurred_at: datetime
    actor: Actor
    payload: dict[str, object]


class CaseQueries(Protocol):
    def detail(self, case_id: uuid.UUID) -> CaseDetail | None: ...

    def cases(
        self, where: CaseFilter, after: uuid.UUID | None, limit: int
    ) -> list[ReconciliationCase]:
        """Ordered by ID, those after ``after``."""
        ...

    def history(self, case_id: uuid.UUID) -> list[HistoryEntry] | None:
        """The case's audited events, oldest first; ``None`` when the case does not exist."""
        ...
