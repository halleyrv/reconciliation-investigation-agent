import uuid

from recon.investigation.application.ports import InvestigationUnitOfWork
from recon.investigation.application.update_case import StaleVersion
from recon.investigation.domain.events import CaseResolved
from recon.shared_kernel.ports import Clock


class CloseSupersededCase:
    """Resolve the case of a discrepancy that a replacing run no longer finds (D3)."""

    def __init__(self, uow: InvestigationUnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def __call__(self, discrepancy_id: uuid.UUID) -> None:
        """Idempotent: no case, or one already closed, is left as it is. A concurrent update
        raises ``StaleVersion`` and writes nothing; the event's redelivery retries it."""
        with self._uow as uow:
            case = uow.cases.find_by_discrepancy(discrepancy_id)
            # a case left on an earlier discrepancy by replacements never delivered (like OpenCase)
            earlier = uow.discrepancies.predecessor(discrepancy_id)
            while case is None and earlier is not None:
                case = uow.cases.find_by_discrepancy(earlier)
                earlier = uow.discrepancies.predecessor(earlier)
            if case is None or case.closed:
                return
            closed = case.closed_as_superseded(self._clock.now())
            if not uow.cases.close(closed, case.version):
                raise StaleVersion(f"case {case.id} was changed while it was being closed")
            assert closed.closed_at is not None and closed.close_reason is not None
            uow.add_event(
                CaseResolved(
                    occurred_at=closed.closed_at,
                    case_id=closed.id,
                    version=closed.version,
                    close_reason=closed.close_reason.value,
                )
            )
            uow.commit()
