import uuid
from dataclasses import dataclass
from datetime import datetime

from recon.investigation.application.ports import InvestigationUnitOfWork
from recon.investigation.domain.case import Priority, ReconciliationCase
from recon.investigation.domain.events import CaseCarriedOver, CaseOpened
from recon.shared_kernel.ports import Clock, IdGenerator


class DiscrepancyNotFound(Exception):
    pass


class DiscrepancyRetired(Exception):
    """A replacing run superseded the discrepancy: its case, if any, lives on elsewhere."""


@dataclass(frozen=True, slots=True)
class Opened:
    case: ReconciliationCase
    created: bool


class OpenCase:
    """Open the one case of a discrepancy. Idempotent: an existing case is returned as is.
    A discrepancy a replacing run found again takes over the case of the one it replaces
    (D3), also across replacements whose events were not delivered yet."""

    def __init__(self, uow: InvestigationUnitOfWork, clock: Clock, ids: IdGenerator) -> None:
        self._uow = uow
        self._clock = clock
        self._ids = ids

    def __call__(self, discrepancy_id: uuid.UUID) -> Opened:
        with self._uow as uow:
            existing = uow.cases.find_by_discrepancy(discrepancy_id)
            if existing is not None:
                return Opened(existing, created=False)
            discrepancy = uow.discrepancies.lock_for_case(discrepancy_id)
            if discrepancy is None:
                raise DiscrepancyNotFound(f"discrepancy {discrepancy_id} does not exist")
            if discrepancy.superseded:
                raise DiscrepancyRetired(f"discrepancy {discrepancy_id} was superseded")
            at = self._clock.now()
            carried = self._carry_over(uow, discrepancy_id, at)
            if carried is not None:
                return Opened(carried, created=False)
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

    def _carry_over(
        self, uow: InvestigationUnitOfWork, discrepancy_id: uuid.UUID, at: datetime
    ) -> ReconciliationCase | None:
        """The case of the nearest earlier discrepancy it replaces, moved to this one."""
        earlier = uow.discrepancies.predecessor(discrepancy_id)
        while earlier is not None:
            case = uow.cases.find_by_discrepancy(earlier)
            if case is not None:
                moved = case.carried_over(discrepancy_id)
                if not uow.cases.carry_over(moved, earlier):
                    # a concurrent delivery of the other event moved it first
                    winner = uow.cases.find_by_discrepancy(discrepancy_id)
                    assert winner is not None
                    return winner
                uow.add_event(
                    CaseCarriedOver(
                        occurred_at=at,
                        case_id=case.id,
                        from_discrepancy_id=earlier,
                        to_discrepancy_id=discrepancy_id,
                    )
                )
                uow.commit()
                return moved
            earlier = uow.discrepancies.predecessor(earlier)
        return None
