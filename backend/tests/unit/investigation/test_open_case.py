import uuid
from datetime import UTC, datetime

import pytest

from recon.investigation.adapters.inbound.events import on_discrepancy_detected
from recon.investigation.adapters.outbound.memory import InMemoryInvestigationUnitOfWork
from recon.investigation.application.open_case import DiscrepancyNotFound, OpenCase
from recon.investigation.application.ports import DiscrepancyView
from recon.investigation.domain.case import CaseStatus, Priority, ReconciliationCase
from recon.investigation.domain.events import CaseOpened
from recon.shared_kernel.actor import Actor
from recon.shared_kernel.events import OutboxMessage
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


def test_a_case_opened_concurrently_is_returned_instead_of_a_second_one() -> None:
    winner = ReconciliationCase.open(uuid.UUID(int=77), DISCREPANCY, Priority.LOW, AT)
    uow = InMemoryInvestigationUnitOfWork(
        [DiscrepancyView(DISCREPANCY, "high")], opened_concurrently=winner
    )

    opened = _open_case(uow)(DISCREPANCY)

    assert not opened.created and opened.case == winner
    assert uow.committed.events == []


def test_the_discrepancy_detected_handler_opens_the_case_from_the_event_payload() -> None:
    uow = _uow()

    on_discrepancy_detected(_open_case(uow))(
        OutboxMessage(
            outbox="recon.outbox",
            id=1,
            event_type="DiscrepancyDetected",
            event_version=1,
            payload={"discrepancy_id": str(DISCREPANCY), "type": "fee_mismatch", "delta_minor": 5},
            created_at=AT,
            actor=Actor.system("recon-reconcile"),
            aggregate_type="Discrepancy",
            aggregate_id=DISCREPANCY,
        )
    )

    [case] = uow.committed.cases.values()
    assert case.discrepancy_id == DISCREPANCY


@pytest.mark.parametrize(
    ("status", "closed_at", "version"),
    [
        (CaseStatus.OPEN, None, 0),
        (CaseStatus.OPEN, AT, 1),
        (CaseStatus.RESOLVED, None, 1),
        (CaseStatus.ESCALATED, None, 1),
    ],
)
def test_a_case_rejects_a_version_below_one_and_a_close_time_that_contradicts_its_status(
    status: CaseStatus, closed_at: datetime | None, version: int
) -> None:
    with pytest.raises(ValueError):
        ReconciliationCase(
            uuid.UUID(int=1), DISCREPANCY, status, Priority.LOW, AT, version, closed_at=closed_at
        )
