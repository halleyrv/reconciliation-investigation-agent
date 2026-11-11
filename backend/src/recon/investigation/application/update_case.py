import uuid
from enum import Enum
from typing import Literal

from recon.investigation.application.ports import InvestigationUnitOfWork
from recon.investigation.domain.case import Priority, ReconciliationCase
from recon.investigation.domain.events import CaseUpdated
from recon.shared_kernel.ports import Clock


class CaseNotFound(Exception):
    def __init__(self, case_id: uuid.UUID) -> None:
        super().__init__(f"no case {case_id}")


class StaleVersion(Exception):
    pass


class _Unchanged(Enum):
    UNCHANGED = "unchanged"


UNCHANGED: Literal[_Unchanged.UNCHANGED] = _Unchanged.UNCHANGED  # a field the update keeps


class UpdateCase:
    """Change a case's priority or assignee (D1). The caller names the version it read; any
    other current version refuses the update and changes nothing (optimistic lock)."""

    def __init__(self, uow: InvestigationUnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def __call__(
        self,
        case_id: uuid.UUID,
        *,
        expected_version: int,
        priority: Priority | _Unchanged = UNCHANGED,
        assignee_id: str | _Unchanged | None = UNCHANGED,
    ) -> ReconciliationCase:
        if priority is UNCHANGED and assignee_id is UNCHANGED:
            raise ValueError("nothing to change: name a priority or an assignee")
        with self._uow as uow:
            case = uow.cases.get(case_id)
            if case is None:
                raise CaseNotFound(case_id)
            if case.version != expected_version:
                raise StaleVersion(
                    f"version {expected_version} is not the current version {case.version}"
                )
            updated = case.reassigned(
                case.priority if priority is UNCHANGED else priority,
                case.assignee_id if assignee_id is UNCHANGED else assignee_id,
            )
            if not uow.cases.update(updated, expected_version):
                raise StaleVersion(f"version {expected_version} was changed by another update")
            uow.add_event(
                CaseUpdated(
                    occurred_at=self._clock.now(),
                    case_id=case_id,
                    version=updated.version,
                    priority=updated.priority.value,
                    assignee_id=updated.assignee_id,
                )
            )
            uow.commit()
            return updated
