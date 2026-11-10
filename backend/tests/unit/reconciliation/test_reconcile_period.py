import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Self

import pytest

from recon.reconciliation.adapters.outbound.memory import InMemoryReconciliationUnitOfWork
from recon.reconciliation.application.load_reference_data import LoadReferenceData
from recon.reconciliation.application.reconcile_period import (
    MissingReferenceData,
    PeriodOverlaps,
    ReconcilePeriod,
    RunFailed,
    RunInProgress,
)
from recon.reconciliation.domain.events import DiscrepancyDetected
from recon.reconciliation.domain.results import Period
from recon.reconciliation.domain.run import ReconciliationRun, RunStatus
from recon.shared_kernel.ports import FixedClock, SequenceIdGenerator

from .book import CALENDAR, MONDAY, SCHEDULE, Book, clean_book

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

    with pytest.raises(RunFailed, match="injected failure") as raised:
        _reconcile(uow)(OCTOBER)
    assert isinstance(raised.value.__cause__, RuntimeError)

    [run] = uow.committed.runs.values()
    assert (run.status, run.finished_at) == (RunStatus.FAILED, NOW)
    assert (uow.committed.groups, uow.committed.discrepancies, uow.committed.events) == ({}, {}, [])


def test_a_failed_run_does_not_block_a_new_run_of_the_same_period() -> None:
    uow = _uow(fail_on_discrepancy=1)
    reconcile = _reconcile(uow)
    with pytest.raises(RunFailed):
        reconcile(OCTOBER)
    uow.fail_on_discrepancy = None  # the cause went away

    retried = reconcile(OCTOBER)

    statuses = sorted(r.status.value for r in uow.committed.runs.values())
    assert statuses == ["completed", "failed"]
    assert retried.status is RunStatus.COMPLETED
    assert len(uow.committed.discrepancies) == 2


def test_a_run_still_in_progress_is_reported_not_returned_as_a_result() -> None:
    uow = _uow()
    running = ReconciliationRun.start(uuid.uuid4(), OCTOBER, "v1", NOW)
    with uow:
        uow.runs.add(running)
        uow.commit()

    with pytest.raises(RunInProgress, match=str(running.id)):
        _reconcile(uow)(OCTOBER)

    assert uow.committed.runs == {running.id: running}


class _DatabaseGone(InMemoryReconciliationUnitOfWork):
    """Fails the output transaction and then the transaction that marks the run failed."""

    def __enter__(self) -> Self:
        super().__enter__()
        save = self.runs.save

        def failing_save(run: ReconciliationRun) -> None:
            if run.status is RunStatus.FAILED:
                raise ConnectionError("database unavailable")
            save(run)

        self.runs.save = failing_save  # type: ignore[method-assign]
        return self


def test_the_original_error_survives_when_the_run_cannot_be_marked_failed() -> None:
    uow = _DatabaseGone(_book_with_two_anomalies().snapshot(), (SCHEDULE,), CALENDAR.holidays, 1)

    with pytest.raises(RunFailed, match="injected failure") as raised:
        _reconcile(uow)(OCTOBER)

    assert isinstance(raised.value.__cause__, RuntimeError)
    assert any("could not be marked failed" in note for note in raised.value.__notes__)
    [run] = uow.committed.runs.values()
    assert run.status is RunStatus.RUNNING


MONDAY_ONLY = Period(MONDAY, MONDAY)
TUESDAY_ONLY = Period(MONDAY + timedelta(days=1), MONDAY + timedelta(days=1))


def _two_days_uow() -> InMemoryReconciliationUnitOfWork:
    book = clean_book()
    book.replace_fee("FEE-000001", 1)
    book.sale(4, 2_000, day=TUESDAY_ONLY.start, batch="STL-000002")
    book.replace_fee("FEE-000004", 2)
    book.close()
    book.close("STL-000002", TUESDAY_ONLY.start)
    return InMemoryReconciliationUnitOfWork(book.snapshot(), (SCHEDULE,), CALENDAR.holidays)


def test_a_run_reconciles_only_the_records_of_its_period() -> None:
    uow = _two_days_uow()
    reconcile = _reconcile(uow)

    monday, tuesday = reconcile(MONDAY_ONLY), reconcile(TUESDAY_ONLY)

    found = {
        run: sorted(r.external_id for d in ds for r in d.records)
        for run, ds in (
            (rid, [d for r, d, _ in uow.committed.discrepancies.values() if r == rid])
            for rid in (monday.id, tuesday.id)
        )
    }
    assert found == {
        monday.id: ["FEE-000001", "PAY-000001"],
        tuesday.id: ["FEE-000004", "PAY-000004"],
    }
    assert len(uow.committed.groups) == 2


def test_a_period_overlapping_a_live_run_of_the_ruleset_is_refused() -> None:
    uow = _two_days_uow()
    reconcile = _reconcile(uow)
    reconcile(MONDAY_ONLY)

    with pytest.raises(PeriodOverlaps, match=r"2026-10-05 to 2026-10-05"):
        reconcile(Period(MONDAY, TUESDAY_ONLY.end))

    assert len(uow.committed.runs) == 1
    assert reconcile(Period(MONDAY, TUESDAY_ONLY.end), "v2").status is RunStatus.COMPLETED


def test_a_fee_with_no_schedule_fails_the_run_until_the_schedule_is_loaded() -> None:
    uow = InMemoryReconciliationUnitOfWork(
        _book_with_two_anomalies().snapshot(), (), CALENDAR.holidays
    )
    reconcile = _reconcile(uow)

    with pytest.raises(RunFailed, match="no fee schedule for gateway_a processing") as raised:
        reconcile(OCTOBER)
    assert isinstance(raised.value.__cause__, MissingReferenceData)
    [failed] = uow.committed.runs.values()
    assert failed.status is RunStatus.FAILED
    assert uow.committed.discrepancies == {}

    LoadReferenceData(uow, SequenceIdGenerator())((SCHEDULE,), frozenset())
    assert reconcile(OCTOBER).status is RunStatus.COMPLETED


def test_a_period_in_a_year_with_no_loaded_calendar_fails_the_run() -> None:
    uow = InMemoryReconciliationUnitOfWork(
        _book_with_two_anomalies().snapshot(), (SCHEDULE,), CALENDAR.holidays
    )

    with pytest.raises(RunFailed, match="no bank holiday calendar for 2027"):
        _reconcile(uow)(Period(date(2026, 12, 1), date(2027, 1, 31)))
