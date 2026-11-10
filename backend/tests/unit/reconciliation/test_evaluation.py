from datetime import UTC, date, datetime

import pytest

from recon.reconciliation.adapters.outbound.memory import InMemoryReconciliationUnitOfWork
from recon.reconciliation.application.evaluate_run import EvaluateRun, NoCompletedRun
from recon.reconciliation.application.evaluation import Finding, Link, evaluate
from recon.reconciliation.application.reconcile_period import ReconcilePeriod
from recon.reconciliation.domain.results import Period
from recon.shared_kernel.ports import FixedClock, SequenceIdGenerator

from .book import CALENDAR, SCHEDULE, clean_book

# The book's payouts are dated 2026-10-07, the due date of a period ending on Monday the 5th.
COVERED = Period(date(2026, 10, 1), date(2026, 10, 5))
NOW = datetime(2026, 11, 10, tzinfo=UTC)


def _f(kind: str, *ids: str, delta: int = 0) -> Finding:
    return Finding(kind, frozenset(("payments", i) for i in ids), delta)


LINK_1 = Link("ORD-1", "PAY-1", "STL-1", "BNK-1")
LINK_2 = Link("ORD-2", "PAY-2", "STL-1", "BNK-1")


def test_a_perfect_engine_scores_100_percent_per_type_and_for_links() -> None:
    expected = [_f("fee_mismatch", "P1", delta=37), _f("underpayment", "P2", delta=-5)]

    result = evaluate(expected, list(reversed(expected)), {LINK_1, LINK_2}, {LINK_1, LINK_2})

    assert [(s.type, s.precision, s.recall) for s in result.types] == [
        ("fee_mismatch", 1.0, 1.0),
        ("underpayment", 1.0, 1.0),
    ]
    assert (result.link_precision, result.link_recall) == (1.0, 1.0)
    assert result.perfect


def test_misses_extras_and_wrong_deltas_are_listed_and_scored() -> None:
    expected = [_f("fee_mismatch", "P1", delta=37), _f("fee_mismatch", "P2", delta=10)]
    detected = [
        _f("fee_mismatch", "P1", delta=36),
        _f("fee_mismatch", "P3", delta=10),
        _f("reference_mismatch", "P2"),
    ]

    result = evaluate(expected, detected, {LINK_1, LINK_2}, {LINK_1})

    scores = {
        s.type: (s.expected, s.detected, s.matched, s.precision, s.recall) for s in result.types
    }
    assert scores == {
        "fee_mismatch": (2, 2, 1, 0.5, 0.5),
        "reference_mismatch": (0, 1, 0, 0.0, None),
    }
    assert result.missed == (_f("fee_mismatch", "P2", delta=10),)
    assert set(result.unexpected) == {
        _f("fee_mismatch", "P3", delta=10),
        _f("reference_mismatch", "P2"),
    }
    assert result.delta_mismatches == ((_f("fee_mismatch", "P1", delta=37), 36),)
    assert (result.link_precision, result.link_recall) == (1.0, 0.5)
    assert result.missed_links == (LINK_2,)
    assert not result.perfect


def test_nothing_expected_and_nothing_found_is_perfect_with_no_rates() -> None:
    result = evaluate([], [], set(), set())

    assert result.types == ()
    assert (result.link_precision, result.link_recall) == (None, None)
    assert result.perfect


def test_evaluate_run_scores_the_completed_run_of_the_period() -> None:
    book = clean_book()
    book.replace_fee("FEE-000002", 1)
    book.close()
    uow = InMemoryReconciliationUnitOfWork(book.snapshot(), (SCHEDULE,), CALENDAR.holidays)
    expected_fee = Finding(
        "fee_mismatch", frozenset({("payments", "PAY-000002"), ("fees", "FEE-000002")}), 1 - 388
    )
    links = {Link(f"ORD-00000{n}", f"PAY-00000{n}", "STL-000001", "BNK-000001") for n in (1, 3)}
    with pytest.raises(NoCompletedRun, match="no completed v1 run"):
        EvaluateRun(uow)(COVERED, [expected_fee], links)
    run = ReconcilePeriod(uow, FixedClock(NOW), SequenceIdGenerator())(COVERED)

    evaluated, result = EvaluateRun(uow)(COVERED, [expected_fee], links)

    assert evaluated == run
    assert result.perfect
    assert (result.links_matched, result.types[0].matched) == (2, 1)


def test_a_duplicated_detection_is_unexpected_and_not_perfect() -> None:
    finding = _f("fee_mismatch", "P1", delta=37)

    result = evaluate([finding], [finding, finding], set(), set())

    assert result.unexpected == (finding,)
    assert [(s.expected, s.detected, s.matched) for s in result.types] == [(1, 2, 1)]
    assert not result.perfect
