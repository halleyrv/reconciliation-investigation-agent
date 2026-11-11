"""AC-2b.1: each anomaly type through the MatchingEngine, asserting type, records and delta.

Every test also asserts the full list of discrepancies, so a symptom reported twice by a
second rule (assumption B1) fails it, and which orders keep their clean link.
"""

import random
from dataclasses import replace
from datetime import date, timedelta

import pytest

from recon.reconciliation.domain.records import BankTransaction, Order, Source, SourceConflict

from .book import CALENDAR, MONDAY, Book, at, clean_book, found, linked_orders, ref, usd

ORD, PAY, RFD, FEE, STL, BNK, AUT = (
    Source.ORDERS,
    Source.PAYMENTS,
    Source.REFUNDS,
    Source.FEES,
    Source.SETTLEMENTS,
    Source.BANK_TRANSACTIONS,
    Source.AUTHORIZATIONS,
)
ALL = {"ORD-000001", "ORD-000002", "ORD-000003"}


def test_a_clean_book_has_no_discrepancy_and_one_balanced_batch_group() -> None:
    book = clean_book()
    book.close()

    result = book.run()

    assert found(result) == []
    assert linked_orders(result) == ALL
    [group] = result.groups
    assert group.rule_code == "settlement_batch"
    roles = sorted((m.role, m.ref.external_id) for m in group.members)
    assert roles == sorted(
        [("settlement", "STL-000001"), ("payout", "BNK-000001")]
        + [(role, f"{prefix}-00000{n}") for n in (1, 2, 3) for role, prefix in
           (("order", "ORD"), ("payment", "PAY"), ("fee", "FEE"))]
    )  # fmt: skip


def test_duplicate_payment() -> None:
    book = clean_book()
    book.pay("PAY-000099", "ORD-000001", 10_000, at(MONDAY, 10, 5), batch="STL-000001")
    book.close()

    result = book.run()

    records = frozenset({ref(ORD, "ORD-000001"), ref(PAY, "PAY-000001"), ref(PAY, "PAY-000099")})
    assert found(result) == [("duplicate_payment", records, 10_000)]
    assert linked_orders(result) == ALL - {"ORD-000001"}


def test_unauthorized_refund() -> None:
    book = clean_book()
    book.refund("RFD-000001", book.payments[0], 4_000, authorized=False)
    book.close()

    result = book.run()

    records = frozenset({ref(ORD, "ORD-000001"), ref(PAY, "PAY-000001"), ref(RFD, "RFD-000001")})
    assert found(result) == [("unauthorized_refund", records, -4_000)]
    assert linked_orders(result) == ALL - {"ORD-000001"}


def test_an_authorized_refund_is_clean() -> None:
    book = clean_book()
    book.refund("RFD-000001", book.payments[0], 4_000, authorized=True)
    book.close()

    result = book.run()

    assert found(result) == []
    assert linked_orders(result) == ALL


def test_a_refund_authorized_for_less_or_after_the_fact_is_unauthorized() -> None:
    book = clean_book()
    book.refund("RFD-000001", book.payments[0], 4_000, authorized=True)
    book.refund("RFD-000002", book.payments[1], 3_000, authorized=True)
    first, second = book.authorizations
    book.authorizations = [
        replace(first, max_amount=usd(3_999)),
        replace(second, approved_at=book.refunds[1].refunded_at),
    ]
    book.close()

    result = book.run()

    assert [(t, d) for t, _, d in found(result)] == [
        ("unauthorized_refund", -4_000),
        ("unauthorized_refund", -3_000),
    ]
    assert ref(AUT, "AUT-000001") in found(result)[0][1]


def test_fee_mismatch() -> None:
    book = clean_book()
    book.replace_fee("FEE-000002", book.fees[1].amount.amount_minor + 37)
    book.close()  # the gateway nets the fee it charged, so the payout still matches

    result = book.run()

    records = frozenset({ref(PAY, "PAY-000002"), ref(FEE, "FEE-000002")})
    assert found(result) == [("fee_mismatch", records, 37)]
    assert linked_orders(result) == ALL - {"ORD-000002"}


def test_missing_in_orders() -> None:
    book = clean_book()
    book.pay("PAY-000099", "ORD-000099", 7_700, at(MONDAY, 11), batch="STL-000001")
    book.close()

    result = book.run()

    records = frozenset({ref(PAY, "PAY-000099"), ref(FEE, "FEE-000099")})
    assert found(result) == [("missing_in_orders", records, 7_700)]
    assert linked_orders(result) == ALL


def test_missing_in_bank() -> None:
    book = clean_book()
    book.close()
    net = book.settlements[0].net_amount.amount_minor
    book.bank.clear()

    result = book.run()

    assert found(result) == [("missing_in_bank", frozenset({ref(STL, "STL-000001")}), -net)]
    assert linked_orders(result) == set()


def test_missing_in_gateway_for_a_payout_of_an_unknown_batch() -> None:
    book = clean_book()
    book.close()
    book.bank.append(
        BankTransaction(
            "BNK-000099", "credit", date(2026, 10, 8), usd(55_000), "GATEWAY_A PAYOUT STL-000099 X"
        )
    )

    result = book.run()

    assert found(result) == [("missing_in_gateway", frozenset({ref(BNK, "BNK-000099")}), 55_000)]
    assert linked_orders(result) == ALL


def test_missing_in_gateway_for_an_order_nobody_paid() -> None:
    book = clean_book()
    book.orders.append(Order("ORD-000004", at(MONDAY, 12), usd(9_900)))
    book.close()

    result = book.run()

    assert found(result) == [("missing_in_gateway", frozenset({ref(ORD, "ORD-000004")}), -9_900)]
    assert linked_orders(result) == ALL


def test_underpayment() -> None:
    book = clean_book()
    book.payments.pop(0)
    book.fees.pop(0)
    book.pay("PAY-000001", "ORD-000001", 8_000, at(MONDAY, 10), batch="STL-000001")
    book.close()

    result = book.run()

    records = frozenset({ref(ORD, "ORD-000001"), ref(PAY, "PAY-000001")})
    assert found(result) == [("underpayment", records, -2_000)]
    assert linked_orders(result) == ALL - {"ORD-000001"}


def test_settlement_delayed() -> None:
    book = clean_book()
    book.close()
    credit = book.bank[0]
    book.bank[0] = replace(credit, value_date=CALENDAR.add_business_days(credit.value_date, 1))

    result = book.run()

    records = frozenset({ref(STL, "STL-000001"), ref(BNK, "BNK-000001")})
    assert found(result) == [("settlement_delayed", records, 0)]
    assert linked_orders(result) == set()


def test_amount_mismatch_between_the_bank_credit_and_the_settlement() -> None:
    book = clean_book()
    book.close()
    book.bank[0] = replace(book.bank[0], amount=usd(book.bank[0].amount.amount_minor - 1_250))

    result = book.run()

    records = frozenset({ref(STL, "STL-000001"), ref(BNK, "BNK-000001")})
    assert found(result) == [("amount_mismatch", records, -1_250)]
    assert linked_orders(result) == set()


def test_amount_mismatch_between_the_settlement_and_its_members() -> None:
    book = clean_book()
    book.close()
    declared = book.settlements[0].net_amount.amount_minor + 300
    book.settlements[0] = replace(book.settlements[0], net_amount=usd(declared))
    book.bank[0] = replace(book.bank[0], amount=usd(declared))

    result = book.run()

    assert found(result) == [("amount_mismatch", frozenset({ref(STL, "STL-000001")}), 300)]
    assert linked_orders(result) == set()


def test_reference_mismatch_for_an_order_reference_that_resolves_only_when_normalized() -> None:
    book = clean_book()
    book.payments[0] = replace(book.payments[0], order_ref="ord_000001")
    book.close()

    result = book.run()

    records = frozenset({ref(ORD, "ORD-000001"), ref(PAY, "PAY-000001")})
    assert found(result) == [("reference_mismatch", records, 0)]
    assert linked_orders(result) == ALL - {"ORD-000001"}


def test_reference_mismatch_for_a_refund_of_an_unknown_payment() -> None:
    book = clean_book()
    refund = book.refund("RFD-000001", book.payments[0], 1_000, authorized=True)
    book.refunds[0] = replace(refund, payment_ref="PAY-000404")
    book.close()

    result = book.run()

    assert found(result) == [("reference_mismatch", frozenset({ref(RFD, "RFD-000001")}), 0)]


def test_sequence_violation_for_a_payment_before_its_order() -> None:
    book = clean_book()
    order = book.orders[2]
    book.orders[2] = replace(order, placed_at=book.payments[2].captured_at + timedelta(minutes=9))
    book.close()

    result = book.run()

    records = frozenset({ref(ORD, "ORD-000003"), ref(PAY, "PAY-000003")})
    assert found(result) == [("sequence_violation", records, 0)]
    assert linked_orders(result) == ALL - {"ORD-000003"}


def test_duplicate_refund() -> None:
    book = clean_book()
    book.refund("RFD-000001", book.payments[1], 6_000, authorized=True)
    book.refund("RFD-000002", book.payments[1], 6_000, authorized=False, minutes=90)
    book.close()

    result = book.run()

    records = frozenset(
        {
            ref(ORD, "ORD-000002"),
            ref(PAY, "PAY-000002"),
            ref(RFD, "RFD-000001"),
            ref(RFD, "RFD-000002"),
            ref(AUT, "AUT-000001"),
        }
    )
    assert found(result) == [("duplicate_refund", records, -6_000)]
    assert linked_orders(result) == ALL - {"ORD-000002"}


def test_source_conflict_once_per_re_sent_record() -> None:
    book = clean_book()
    book.conflicts += [SourceConflict(ORD, "ORD-000003"), SourceConflict(ORD, "ORD-000003")]
    book.close()

    result = book.run()

    assert found(result) == [("source_conflict", frozenset({ref(ORD, "ORD-000003")}), 0)]
    assert linked_orders(result) == ALL - {"ORD-000003"}


def test_the_result_does_not_depend_on_input_order() -> None:
    book = clean_book()
    book.sale(4, 2_000, day=MONDAY + timedelta(days=1), batch="STL-000002")
    book.refund("RFD-000001", book.payments[0], 4_000, authorized=False)
    book.replace_fee("FEE-000002", 1)
    book.close()
    book.close("STL-000002", MONDAY + timedelta(days=1))
    expected = book.run()

    rng = random.Random(7)
    for records in (
        book.orders,
        book.payments,
        book.refunds,
        book.fees,
        book.settlements,
        book.bank,
    ):
        rng.shuffle(records)

    assert book.run() == expected
    assert len(expected.groups) == 2


def test_an_empty_book_reconciles_to_nothing() -> None:
    result = Book().run()

    assert result.discrepancies == ()
    assert result.groups == ()


def test_a_refund_with_both_references_dangling_is_one_reference_mismatch() -> None:
    book = clean_book()
    refund = book.refund("RFD-000001", book.payments[0], 1_000, authorized=True)
    book.refunds[0] = replace(refund, payment_ref="PAY-000404", settlement_ref="STL-000404")
    book.close()

    result = book.run()

    assert found(result) == [("reference_mismatch", frozenset({ref(RFD, "RFD-000001")}), 0)]


def test_overpayment() -> None:
    book = clean_book()
    book.payments.pop(2)
    book.fees.pop(2)
    book.pay("PAY-000003", "ORD-000003", 7_000, at(MONDAY, 10), batch="STL-000001")
    book.close()

    result = book.run()

    records = frozenset({ref(ORD, "ORD-000003"), ref(PAY, "PAY-000003")})
    assert found(result) == [("overpayment", records, 7_000 - 5_050)]
    assert linked_orders(result) == ALL - {"ORD-000003"}


@pytest.mark.parametrize(("paid", "expected"), [(5_050, []), (5_051, [1])])
def test_overpayment_starts_one_cent_above_the_order_total(paid: int, expected: list[int]) -> None:
    book = clean_book()
    book.payments.pop(2)
    book.fees.pop(2)
    book.pay("PAY-000003", "ORD-000003", paid, at(MONDAY, 10), batch="STL-000001")
    book.close()

    records = frozenset({ref(ORD, "ORD-000003"), ref(PAY, "PAY-000003")})
    assert found(book.run()) == [("overpayment", records, d) for d in expected]


def test_a_credit_exactly_on_the_due_date_is_on_time() -> None:
    book = clean_book()
    book.close()

    assert book.bank[0].value_date == CALENDAR.add_business_days(MONDAY, 2)
    assert found(book.run()) == []


def test_sequence_violations_of_capture_credit_and_refund_order() -> None:
    book = clean_book()
    refund = book.refund("RFD-000001", book.payments[1], 1_000, authorized=True)
    book.refunds[0] = replace(refund, refunded_at=book.payments[1].captured_at)
    book.authorizations[0] = replace(
        book.authorizations[0], approved_at=book.payments[1].captured_at - timedelta(minutes=1)
    )
    book.payments[2] = replace(book.payments[2], captured_at=at(MONDAY + timedelta(days=1), 1))
    book.close()
    book.bank[0] = replace(book.bank[0], value_date=MONDAY - timedelta(days=1))

    kinds = {(t, tuple(sorted(r.external_id for r in refs))) for t, refs, _ in found(book.run())}

    assert kinds == {
        ("sequence_violation", ("PAY-000002", "RFD-000001")),
        ("sequence_violation", ("PAY-000003", "STL-000001")),
        ("sequence_violation", ("BNK-000001", "STL-000001")),
    }


def test_reference_mismatch_for_a_fee_of_an_unknown_payment_and_an_unknown_batch() -> None:
    book = clean_book()
    book.fees[0] = replace(book.fees[0], payment_ref="PAY-000404")
    book.payments[1] = replace(book.payments[1], settlement_ref="STL-000404")
    book.fees[1] = replace(book.fees[1], settlement_ref="STL-000404")
    book.close()

    result = book.run()

    refs = {next(iter(r)).external_id for t, r, _ in found(result) if t == "reference_mismatch"}
    assert refs == {"FEE-000001", "PAY-000002", "FEE-000002"}
