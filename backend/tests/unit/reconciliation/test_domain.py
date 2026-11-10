from datetime import date

import pytest

from recon.reconciliation.domain.calendar import BusinessCalendar
from recon.reconciliation.domain.fees import FeeSchedule
from recon.reconciliation.domain.records import RecordRef, Source
from recon.reconciliation.domain.results import Discrepancy, DiscrepancyType, Period
from recon.shared_kernel.money import Money

from .book import usd

OCTOBER = Period(date(2026, 10, 1), date(2026, 10, 31))


def test_business_days_skip_weekends_and_holidays() -> None:
    calendar = BusinessCalendar(frozenset({date(2026, 10, 9)}))

    assert calendar.add_business_days(date(2026, 10, 5), 2) == date(2026, 10, 7)
    assert calendar.add_business_days(date(2026, 10, 7), 2) == date(2026, 10, 12)  # Fri holiday
    assert calendar.add_business_days(date(2026, 10, 10), 2) == date(2026, 10, 13)  # from Sat


def test_a_fee_is_basis_points_plus_fixed_rounded_once_half_even() -> None:
    schedule = FeeSchedule("gateway_a", "processing", 290, usd(30), date(2026, 1, 1), None)

    assert schedule.fee_for(usd(10_000)) == usd(320)
    assert schedule.fee_for(usd(12_345)) == usd(388)  # 358.005 + 30 -> 388
    assert schedule.fee_for(usd(5_050)) == usd(176)  # 146.45 + 30 -> 176


def test_a_fee_schedule_applies_only_inside_its_half_open_validity() -> None:
    schedule = FeeSchedule(
        "gateway_a", "processing", 290, usd(30), date(2026, 1, 1), date(2026, 2, 1)
    )

    assert schedule.applies_to("gateway_a", "processing", date(2026, 1, 31))
    assert not schedule.applies_to("gateway_a", "processing", date(2026, 2, 1))
    assert not schedule.applies_to("gateway_b", "processing", date(2026, 1, 15))
    with pytest.raises(ValueError, match="valid_until"):
        FeeSchedule("gateway_a", "processing", 290, usd(30), date(2026, 2, 1), date(2026, 2, 1))


def _discrepancy(*ids: str, kind: DiscrepancyType = DiscrepancyType.FEE_MISMATCH) -> Discrepancy:
    records = frozenset(RecordRef(Source.PAYMENTS, i) for i in ids)
    return Discrepancy(kind, records, usd(100), usd(137))


def test_the_fingerprint_depends_on_type_records_and_period_only() -> None:
    first = _discrepancy("PAY-1", "PAY-2").fingerprint(OCTOBER)

    assert first == _discrepancy("PAY-2", "PAY-1").fingerprint(OCTOBER)
    assert len(first) == 64
    assert first != _discrepancy("PAY-1").fingerprint(OCTOBER)
    assert first != _discrepancy("PAY-1", "PAY-2", kind=DiscrepancyType.UNDERPAYMENT).fingerprint(
        OCTOBER
    )
    assert first != _discrepancy("PAY-1", "PAY-2").fingerprint(
        Period(date(2026, 10, 1), date(2026, 10, 30))
    )


def test_a_discrepancy_has_records_and_one_currency() -> None:
    assert _discrepancy("PAY-1").delta_minor == 37
    with pytest.raises(ValueError, match="record"):
        Discrepancy(DiscrepancyType.FEE_MISMATCH, frozenset(), usd(1), usd(2))
    with pytest.raises(ValueError, match="currency"):
        Discrepancy(
            DiscrepancyType.FEE_MISMATCH,
            frozenset({RecordRef(Source.FEES, "FEE-1")}),
            usd(1),
            Money(2, "EUR"),
        )
