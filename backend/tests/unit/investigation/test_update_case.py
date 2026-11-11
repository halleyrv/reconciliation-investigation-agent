"""``UpdateCase``: priority and assignee under an optimistic version check (D1, AC-2c.5)."""

import uuid
from datetime import UTC, datetime

import pytest

from recon.investigation.adapters.outbound.memory import InMemoryInvestigationUnitOfWork
from recon.investigation.application.ports import DiscrepancyView
from recon.investigation.application.update_case import (
    CaseNotFound,
    StaleVersion,
    UpdateCase,
)
from recon.investigation.domain.case import Priority, ReconciliationCase
from recon.investigation.domain.events import CaseUpdated
from recon.shared_kernel.ports import FixedClock

OPENED = datetime(2026, 11, 10, 12, tzinfo=UTC)
AT = datetime(2026, 11, 11, 9, tzinfo=UTC)
CASE = ReconciliationCase.open(uuid.UUID(int=1), uuid.UUID(int=900), Priority.LOW, OPENED)


def _uow() -> InMemoryInvestigationUnitOfWork:
    uow = InMemoryInvestigationUnitOfWork([DiscrepancyView(CASE.discrepancy_id, "low")])
    uow.committed.cases[CASE.id] = CASE
    return uow


def test_an_update_at_the_current_version_changes_the_case_and_emits_case_updated() -> None:
    uow = _uow()

    case = UpdateCase(uow, FixedClock(AT))(
        CASE.id, expected_version=1, priority=Priority.HIGH, assignee_id="analyst-7"
    )

    assert (case.priority, case.assignee_id, case.version) == (Priority.HIGH, "analyst-7", 2)
    assert (case.status, case.opened_at, case.discrepancy_id) == (
        CASE.status,
        CASE.opened_at,
        CASE.discrepancy_id,
    )
    assert uow.committed.cases == {CASE.id: case}
    assert uow.committed.events == [
        CaseUpdated(
            occurred_at=AT, case_id=CASE.id, version=2, priority="high", assignee_id="analyst-7"
        )
    ]


def test_an_omitted_field_keeps_its_value_and_a_null_assignee_unassigns() -> None:
    uow = _uow()
    update = UpdateCase(uow, FixedClock(AT))
    update(CASE.id, expected_version=1, assignee_id="analyst-7")

    kept = update(CASE.id, expected_version=2, priority=Priority.MEDIUM)
    cleared = update(CASE.id, expected_version=3, assignee_id=None)

    assert (kept.priority, kept.assignee_id) == (Priority.MEDIUM, "analyst-7")
    assert (cleared.priority, cleared.assignee_id, cleared.version) == (Priority.MEDIUM, None, 4)


def test_a_stale_version_is_refused_and_changes_nothing() -> None:
    uow = _uow()

    with pytest.raises(StaleVersion, match="version 2 is not the current version 1"):
        UpdateCase(uow, FixedClock(AT))(CASE.id, expected_version=2, priority=Priority.HIGH)

    assert uow.committed.cases == {CASE.id: CASE}
    assert uow.committed.events == []


def test_a_version_taken_by_a_concurrent_update_is_refused() -> None:
    uow = _uow()
    uow.updated_concurrently = True  # another writer commits between our read and our write

    with pytest.raises(StaleVersion):
        UpdateCase(uow, FixedClock(AT))(CASE.id, expected_version=1, priority=Priority.HIGH)

    assert uow.committed.events == []


def test_an_unknown_case_is_refused() -> None:
    with pytest.raises(CaseNotFound):
        UpdateCase(_uow(), FixedClock(AT))(uuid.UUID(int=2), expected_version=1, assignee_id="a")


def test_an_update_with_no_change_is_refused() -> None:
    with pytest.raises(ValueError, match="nothing to change"):
        UpdateCase(_uow(), FixedClock(AT))(CASE.id, expected_version=1)


def test_a_blank_assignee_is_refused() -> None:
    with pytest.raises(ValueError, match="assignee"):
        UpdateCase(_uow(), FixedClock(AT))(CASE.id, expected_version=1, assignee_id=" ")
