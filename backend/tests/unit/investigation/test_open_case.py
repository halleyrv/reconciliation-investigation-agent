import uuid
from datetime import UTC, datetime

import pytest

from recon.investigation.adapters.outbound.memory import InMemoryInvestigationUnitOfWork
from recon.investigation.application.open_case import DiscrepancyNotFound, OpenCase
from recon.investigation.application.ports import DiscrepancyView
from recon.investigation.domain.case import CaseStatus, Priority
from recon.investigation.domain.events import CaseOpened
from recon.shared_kernel.ports import FixedClock, SequenceIdGenerator

AT = datetime(2026, 11, 10, 12, tzinfo=UTC)
DISCREPANCY = uuid.UUID(int=900)


def _open_case(uow: InMemoryInvestigationUnitOfWork) -> OpenCase:
    return OpenCase(uow, FixedClock(AT), SequenceIdGenerator())


def _uow() -> InMemoryInvestigationUnitOfWork:
    return InMemoryInvestigationUnitOfWork([DiscrepancyView(DISCREPANCY, "high")])


def test_opening_a_case_for_a_discrepancy_persists_it_open_and_emits_case_opened() -> None:
    uow = _uow()

    opened = _open_case(uow)(DISCREPANCY)

    assert opened.created
    case = opened.case
    assert (case.discrepancy_id, case.status, case.priority) == (
        DISCREPANCY,
        CaseStatus.OPEN,
        Priority.HIGH,  # the discrepancy's severity
    )
    assert (case.version, case.opened_at, case.assignee_id, case.closed_at) == (1, AT, None, None)
    assert uow.committed.cases == {case.id: case}
    assert uow.committed.events == [
        CaseOpened(occurred_at=AT, case_id=case.id, discrepancy_id=DISCREPANCY, priority="high")
    ]


def test_opening_the_case_again_returns_the_existing_case_and_writes_nothing() -> None:
    uow = _uow()
    first = _open_case(uow)(DISCREPANCY)

    again = _open_case(uow)(DISCREPANCY)

    assert not again.created
    assert again.case == first.case
    assert len(uow.committed.cases) == 1 and len(uow.committed.events) == 1


def test_a_case_for_an_unknown_discrepancy_is_refused_and_nothing_is_written() -> None:
    uow = _uow()

    with pytest.raises(DiscrepancyNotFound, match=str(uuid.UUID(int=1))):
        _open_case(uow)(uuid.UUID(int=1))

    assert uow.committed.cases == {} and uow.committed.events == []
