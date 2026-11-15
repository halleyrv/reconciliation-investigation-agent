"""Cases across a run replacement (D3): a case follows its discrepancy when the replacing run
finds it again (same fingerprint) and closes as superseded when it does not. Events may arrive
in any order and more than once (the relay is at least once and skips a failing row)."""

import dataclasses
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from recon.investigation.adapters.inbound.events import (
    on_discrepancy_detected,
    on_discrepancy_superseded,
)
from recon.investigation.adapters.outbound.memory import InMemoryInvestigationUnitOfWork
from recon.investigation.application.close_case import CloseSupersededCase
from recon.investigation.application.open_case import DiscrepancyRetired, OpenCase
from recon.investigation.application.ports import DiscrepancyView
from recon.investigation.domain.case import CaseStatus, CloseReason, Priority, ReconciliationCase
from recon.investigation.domain.events import CaseCarriedOver, CaseResolved
from recon.shared_kernel.actor import Actor
from recon.shared_kernel.events import OutboxMessage
from recon.shared_kernel.ports import FixedClock, SequenceIdGenerator

OPENED = datetime(2026, 11, 10, 12, tzinfo=UTC)
AT = datetime(2026, 11, 12, 9, tzinfo=UTC)
D1, D2, D3 = (uuid.UUID(int=n) for n in (901, 902, 903))


def _uow(*views: DiscrepancyView) -> InMemoryInvestigationUnitOfWork:
    return InMemoryInvestigationUnitOfWork(views)


def _case_on(uow: InMemoryInvestigationUnitOfWork, discrepancy: uuid.UUID) -> ReconciliationCase:
    """A case someone already worked on: reassigned once, so at version 2."""
    case = ReconciliationCase.open(uuid.UUID(int=1), discrepancy, Priority.LOW, OPENED)
    case = case.reassigned(Priority.HIGH, "analyst-7")
    uow.committed.cases[case.id] = case
    return case


def _open_case(uow: InMemoryInvestigationUnitOfWork) -> OpenCase:
    return OpenCase(uow, FixedClock(AT), SequenceIdGenerator())


def _close_case(uow: InMemoryInvestigationUnitOfWork) -> CloseSupersededCase:
    return CloseSupersededCase(uow, FixedClock(AT))


def _message(event_type: str, payload: dict[str, object]) -> OutboxMessage:
    return OutboxMessage(
        outbox="recon.outbox",
        id=1,
        event_type=event_type,
        event_version=1,
        payload=payload,
        created_at=AT,
        actor=Actor.system("recon-reconcile"),
        aggregate_type="Discrepancy",
        aggregate_id=uuid.UUID(str(payload["discrepancy_id"])),
    )


def _detected(discrepancy: uuid.UUID) -> OutboxMessage:
    return _message("DiscrepancyDetected", {"discrepancy_id": str(discrepancy)})


def _superseded(discrepancy: uuid.UUID, by: uuid.UUID | None) -> OutboxMessage:
    return _message(
        "DiscrepancySuperseded",
        {"discrepancy_id": str(discrepancy), "superseded_by": None if by is None else str(by)},
    )


def test_the_case_of_a_discrepancy_found_again_moves_to_it_keeping_its_state() -> None:
    uow = _uow(
        DiscrepancyView(D1, "low", superseded=True, superseded_by=D2), DiscrepancyView(D2, "low")
    )
    case = _case_on(uow, D1)

    opened = _open_case(uow)(D2)

    moved = dataclasses.replace(case, discrepancy_id=D2)  # status, assignee, version kept
    assert not opened.created
    assert opened.case == moved
    assert uow.committed.cases == {case.id: moved}
    assert uow.committed.events == [
        CaseCarriedOver(
            occurred_at=AT, case_id=case.id, from_discrepancy_id=D1, to_discrepancy_id=D2
        )
    ]


@pytest.mark.parametrize("superseded_first", [True, False])
def test_both_events_of_a_replacement_carry_the_case_over_once_in_either_order(
    superseded_first: bool,
) -> None:
    uow = _uow(
        DiscrepancyView(D1, "low", superseded=True, superseded_by=D2), DiscrepancyView(D2, "low")
    )
    case = _case_on(uow, D1)
    detected = on_discrepancy_detected(_open_case(uow))
    superseded = on_discrepancy_superseded(_open_case(uow), _close_case(uow))
    deliveries: list[Callable[[], None]] = [
        lambda: superseded(_superseded(D1, D2)),
        lambda: detected(_detected(D2)),
    ]

    for deliver in deliveries if superseded_first else deliveries[::-1]:
        deliver()
        deliver()  # redelivered

    assert uow.committed.cases == {case.id: dataclasses.replace(case, discrepancy_id=D2)}
    assert [type(e) for e in uow.committed.events] == [CaseCarriedOver]


def test_a_case_skips_replacements_whose_events_were_never_delivered() -> None:
    uow = _uow(
        DiscrepancyView(D1, "low", superseded=True, superseded_by=D2),
        DiscrepancyView(D2, "low", superseded=True, superseded_by=D3),
        DiscrepancyView(D3, "low"),
    )
    case = _case_on(uow, D1)

    opened = _open_case(uow)(D3)

    assert opened.case == dataclasses.replace(case, discrepancy_id=D3)
    assert uow.committed.events == [
        CaseCarriedOver(
            occurred_at=AT, case_id=case.id, from_discrepancy_id=D1, to_discrepancy_id=D3
        )
    ]


def test_the_case_of_a_discrepancy_not_found_again_closes_resolved_as_superseded() -> None:
    uow = _uow(DiscrepancyView(D1, "low", superseded=True))
    case = _case_on(uow, D1)
    handle = on_discrepancy_superseded(_open_case(uow), _close_case(uow))

    handle(_superseded(D1, None))
    handle(_superseded(D1, None))  # redelivered: already closed

    closed = dataclasses.replace(
        case,
        status=CaseStatus.RESOLVED,
        closed_at=AT,
        close_reason=CloseReason.SUPERSEDED,
        version=3,
    )
    assert uow.committed.cases == {case.id: closed}
    assert uow.committed.events == [
        CaseResolved(occurred_at=AT, case_id=case.id, version=3, close_reason="superseded")
    ]


def test_a_superseded_discrepancy_gets_no_new_case() -> None:
    uow = _uow(DiscrepancyView(D1, "low", superseded=True))

    with pytest.raises(DiscrepancyRetired, match=str(D1)):
        _open_case(uow)(D1)
    on_discrepancy_detected(_open_case(uow))(_detected(D1))  # a late delivery opens nothing

    assert uow.committed.cases == {} and uow.committed.events == []


def test_a_close_reason_belongs_only_to_a_resolved_case() -> None:
    with pytest.raises(ValueError):
        ReconciliationCase(
            uuid.UUID(int=1),
            D1,
            CaseStatus.OPEN,
            Priority.LOW,
            OPENED,
            1,
            close_reason=CloseReason.SUPERSEDED,
        )


def test_a_case_left_behind_by_undelivered_replacements_closes_when_a_later_one_drops_it() -> None:
    # D1 -> D2 was never delivered, then a second replacement no longer finds D2
    uow = _uow(
        DiscrepancyView(D1, "low", superseded=True, superseded_by=D2),
        DiscrepancyView(D2, "low", superseded=True),
    )
    case = _case_on(uow, D1)
    handle = on_discrepancy_superseded(_open_case(uow), _close_case(uow))

    handle(_superseded(D1, D2))  # D2 is retired: nothing to carry over to
    handle(_superseded(D2, None))

    [closed] = uow.committed.cases.values()
    assert (closed.id, closed.discrepancy_id, closed.status, closed.close_reason) == (
        case.id,
        D1,
        CaseStatus.RESOLVED,
        CloseReason.SUPERSEDED,
    )
