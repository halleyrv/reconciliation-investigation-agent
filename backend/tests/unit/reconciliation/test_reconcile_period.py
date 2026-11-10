from datetime import UTC, date, datetime

import pytest

from recon.reconciliation.adapters.outbound.memory import InMemoryReconciliationUnitOfWork
from recon.reconciliation.application.reconcile_period import ReconcilePeriod
from recon.reconciliation.domain.events import DiscrepancyDetected
from recon.reconciliation.domain.results import Period
from recon.reconciliation.domain.run import RunStatus
from recon.shared_kernel.ports import FixedClock, SequenceIdGenerator

from .book import CALENDAR, SCHEDULE, Book, clean_book

OCTOBER = Period(date(2026, 10, 1), date(2026, 10, 31))
NOW = datetime(2026, 11, 10, 8, tzinfo=UTC)


def _book_with_two_anomalies() -> Book:
    book = clean_book()
    book.refund("RFD-000001", book.payments[0], 4_000, authorized=False)
    book.replace_fee("FEE-000002", 1)
    book.close()
    return book


def _uow(fail_on_discrepancy: int | None = None) -> InMemoryReconciliationUnitOfWork:
    return InMemoryReconciliationUnitOfWork(
        _book_with_two_anomalies().snapshot(),
        (SCHEDULE,),
        CALENDAR.holidays,
        fail_on_discrepancy=fail_on_discrepancy,
    )


def _reconcile(uow: InMemoryReconciliationUnitOfWork) -> ReconcilePeriod:
    return ReconcilePeriod(uow, FixedClock(NOW), SequenceIdGenerator())


def test_a_run_records_groups_discrepancies_and_one_event_each_then_completes() -> None:
    uow = _uow()

    run = _reconcile(uow)(OCTOBER)

    assert (run.status, run.finished_at, run.ruleset_version) == (RunStatus.COMPLETED, NOW, "v1")
    state = uow.committed
    assert state.runs == {run.id: run}
    assert len(state.groups) == 1
    kinds = sorted(d.type.value for _, d, _ in state.discrepancies.values())
    assert kinds == ["fee_mismatch", "unauthorized_refund"]
    assert {f for _, d, f in state.discrepancies.values()} == {
        d.fingerprint(OCTOBER) for _, d, _ in state.discrepancies.values()
    }
    assert all(isinstance(e, DiscrepancyDetected) for e in state.events)
    assert {(e.discrepancy_id, e.delta_minor) for e in state.events} == {  # type: ignore[attr-defined]
        (i, d.delta_minor) for i, (_, d, _) in state.discrepancies.items()
    }


def test_reconciling_the_same_period_and_ruleset_again_returns_the_run_and_writes_nothing() -> None:
    uow = _uow()
    first = _reconcile(uow)(OCTOBER)
    before = uow.committed

    again = _reconcile(uow)(OCTOBER)

    assert again == first
    assert uow.committed == before


def test_a_run_failing_halfway_is_failed_and_leaves_no_partial_output() -> None:
    uow = _uow(fail_on_discrepancy=2)

    with pytest.raises(RuntimeError, match="injected failure"):
        _reconcile(uow)(OCTOBER)

    [run] = uow.committed.runs.values()
    assert (run.status, run.finished_at) == (RunStatus.FAILED, NOW)
    assert (uow.committed.groups, uow.committed.discrepancies, uow.committed.events) == ({}, {}, [])


def test_a_failed_run_does_not_block_a_new_run_of_the_same_period() -> None:
    uow = _uow(fail_on_discrepancy=1)
    reconcile = _reconcile(uow)
    with pytest.raises(RuntimeError):
        reconcile(OCTOBER)
    uow.fail_on_discrepancy = None  # the cause went away

    retried = reconcile(OCTOBER)

    statuses = sorted(r.status.value for r in uow.committed.runs.values())
    assert statuses == ["completed", "failed"]
    assert retried.status is RunStatus.COMPLETED
    assert len(uow.committed.discrepancies) == 2
