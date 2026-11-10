import uuid
from dataclasses import dataclass

from recon.investigation.application.ports import InvestigationUnitOfWork
from recon.investigation.domain.case import Priority, ReconciliationCase
from recon.investigation.domain.events import CaseOpened
from recon.shared_kernel.ports import Clock, IdGenerator


class DiscrepancyNotFound(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Opened:
    case: ReconciliationCase
    created: bool


class OpenCase:
    """Open the one case of a discrepancy. Idempotent: an existing case is returned as is."""

    def __init__(self, uow: InvestigationUnitOfWork, clock: Clock, ids: IdGenerator) -> None:
        self._uow = uow
        self._clock = clock
        self._ids = ids

    def __call__(self, discrepancy_id: uuid.UUID) -> Opened:
        with self._uow as uow:
            existing = uow.cases.find_by_discrepancy(discrepancy_id)
            if existing is not None:
                return Opened(existing, created=False)
            discrepancy = uow.discrepancies.get(discrepancy_id)
            if discrepancy is None:
                raise DiscrepancyNotFound(f"discrepancy {discrepancy_id} does not exist")
            at = self._clock.now()
            case = ReconciliationCase.open(
                self._ids.new(), discrepancy_id, Priority(discrepancy.severity), at
            )
            if not uow.cases.add(case):
                # a concurrent caller opened it between our read and our insert
                winner = uow.cases.find_by_discrepancy(discrepancy_id)
                assert winner is not None
                return Opened(winner, created=False)
            uow.add_event(
                CaseOpened(
                    occurred_at=at,
                    case_id=case.id,
                    discrepancy_id=discrepancy_id,
                    priority=case.priority.value,
                )
            )
            uow.commit()
            return Opened(case, created=True)
