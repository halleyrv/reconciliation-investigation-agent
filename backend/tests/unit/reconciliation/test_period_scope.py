"""H1 / ADR-0016: a run reports the discrepancies and groups of its period only.

Rules always see every record, so a cross-period reference never looks dangling. A
discrepancy belongs to the period holding the latest anchor date of its records (the
settlement batch date of the record, else its own date); a match group to the period of
its settlement batch.
"""

from dataclasses import replace
from datetime import date, timedelta

from recon.reconciliation.domain.engine import default_engine
from recon.reconciliation.domain.records import Order, RecordRef, Source
from recon.reconciliation.domain.results import Period, ReconciliationResult

from .book import MONDAY, RULESET, Book, at, found, usd

TUESDAY = MONDAY + timedelta(days=1)
MONDAY_ONLY = Period(MONDAY, MONDAY)
TUESDAY_ONLY = Period(TUESDAY, TUESDAY)


def _two_days() -> Book:
    """Monday: orders 1-2 with a wrong fee on 2. Tuesday: order 3, plus an unauthorized
    refund of Monday's payment 1 that Tuesday's batch absorbs."""
    book = Book()
    book.sale(1, 10_000)
    book.sale(2, 20_000)
    book.replace_fee("FEE-000002", 1)
    book.sale(3, 5_000, day=TUESDAY, batch="STL-000002")
    book.refund("RFD-000001", book.payments[0], 1_000, authorized=False)
    book.refunds[0] = replace(book.refunds[0], settlement_ref="STL-000002")
    book.orders.append(Order("ORD-000009", at(TUESDAY, 8), usd(700)))  # nobody paid it
    book.close()
    book.close("STL-000002", TUESDAY)
    return book


def _run(book: Book, period: Period | None) -> ReconciliationResult:
    return default_engine().run(book.snapshot(), RULESET, period)


def test_a_discrepancy_belongs_to_the_period_of_its_latest_record() -> None:
    book = _two_days()

    monday, tuesday = _run(book, MONDAY_ONLY), _run(book, TUESDAY_ONLY)

    assert [(t, d) for t, _, d in found(monday)] == [("fee_mismatch", 1 - 610)]
    assert sorted((t, d) for t, _, d in found(tuesday)) == [
        ("missing_in_gateway", -700),
        ("unauthorized_refund", -1_000),  # its payment is Monday's, still resolved
    ]


def test_a_match_group_belongs_to_the_period_of_its_settlement_batch() -> None:
    book = _two_days()

    def batches(result: ReconciliationResult) -> set[str]:
        return {
            m.ref.external_id
            for g in result.groups
            for m in g.members
            if m.ref.source is Source.SETTLEMENTS
        }

    assert batches(_run(book, MONDAY_ONLY)) == {"STL-000001"}
    assert batches(_run(book, TUESDAY_ONLY)) == {"STL-000002"}


def test_adjacent_periods_split_the_whole_result_exactly_and_an_empty_period_has_nothing() -> None:
    book = _two_days()
    whole = _run(book, None)
    parts = [_run(book, MONDAY_ONLY), _run(book, TUESDAY_ONLY)]

    assert sorted(d for p in parts for d in found(p)) == sorted(found(whole))
    split = [g for p in parts for g in p.groups]
    assert len(split) == len(whole.groups) and set(split) == set(whole.groups)
    empty = _run(book, Period(date(2030, 1, 1), date(2030, 1, 31)))
    assert (empty.discrepancies, empty.groups) == ((), ())


def test_anchor_dates_follow_the_batch_else_the_record_own_date() -> None:
    snapshot = _two_days().snapshot()

    assert snapshot.anchor_of(RecordRef(Source.REFUNDS, "RFD-000001")) == TUESDAY
    assert snapshot.anchor_of(RecordRef(Source.ORDERS, "ORD-000001")) == MONDAY
    assert snapshot.anchor_of(RecordRef(Source.ORDERS, "ORD-000009")) == TUESDAY
    assert snapshot.anchor_of(RecordRef(Source.BANK_TRANSACTIONS, "BNK-000002")) == TUESDAY
