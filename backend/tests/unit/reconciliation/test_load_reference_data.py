import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from recon.reconciliation.adapters.inbound.ground_truth import read_ground_truth
from recon.reconciliation.adapters.inbound.reference_file import read_reference_file
from recon.reconciliation.adapters.outbound.memory import InMemoryReconciliationUnitOfWork
from recon.reconciliation.application.load_reference_data import (
    LoadReferenceData,
    ReferenceDataConflict,
)
from recon.reconciliation.domain.fees import FeeSchedule
from recon.shared_kernel.ports import SequenceIdGenerator

from .book import Book, usd

REFERENCE_FILE = Path(__file__).parents[3] / "reference" / "gateway-policy-2026.json"
SCALE_CONFIG = Path(__file__).parents[4] / "simulator" / "configs" / "orders-2000.yaml"
POLICIES = Path(__file__).parents[4] / "simulator" / "samples" / "orders-200-seed-42" / "policies"
A = FeeSchedule("gateway_a", "processing", 290, usd(30), date(2026, 1, 1), None)
B = FeeSchedule("gateway_b", "processing", 250, usd(25), date(2026, 1, 1), None)
HOLIDAYS = frozenset({date(2026, 10, 9), date(2026, 10, 20)})


def _load(uow: InMemoryReconciliationUnitOfWork) -> LoadReferenceData:
    return LoadReferenceData(uow, SequenceIdGenerator())


def test_loading_adds_schedules_and_holidays_once() -> None:
    uow = InMemoryReconciliationUnitOfWork(Book().snapshot())

    first = _load(uow)((A, B), HOLIDAYS)
    again = _load(uow)((A, B), HOLIDAYS | {date(2026, 10, 28)})

    assert (first.schedules_added, first.holidays_added) == (2, 2)
    assert (again.schedules_added, again.holidays_added) == (0, 1)
    assert set(uow.committed.fee_schedules.values()) == {A, B}
    assert uow.committed.holidays == HOLIDAYS | {date(2026, 10, 28)}


def test_a_different_schedule_overlapping_a_loaded_one_is_rejected_and_nothing_is_loaded() -> None:
    uow = InMemoryReconciliationUnitOfWork(Book().snapshot())
    _load(uow)((A,), frozenset())
    raised = FeeSchedule("gateway_a", "processing", 300, usd(30), date(2026, 6, 1), None)

    with pytest.raises(ReferenceDataConflict, match="gateway_a processing"):
        _load(uow)((B, raised), HOLIDAYS)

    assert set(uow.committed.fee_schedules.values()) == {A}
    assert uow.committed.holidays == frozenset()


def test_the_committed_reference_file_equals_the_published_gateway_policy() -> None:
    """OD1 and AS3: values transcribed by hand, checked against the policy text, never parsed
    by the engine. The sample's policy lists October; the 2,000-order export publishes the
    policy of ``simulator/configs/orders-2000.yaml``, which covers all of 2026."""
    schedules, holidays, years = read_reference_file(REFERENCE_FILE)
    fee_text = (POLICIES / "fee_schedule.md").read_text()
    published = {
        (gateway, int(bps), int(fixed.replace(".", "")))
        for gateway, bps, fixed in re.findall(
            r"^\| (\S+) \| ([0-9]+) \| ([0-9.]+) \|$", fee_text, re.M
        )
    }
    assert {(s.gateway, s.rate_bps, s.fixed.amount_minor) for s in schedules} == published
    assert all(s.fee_type == "processing" and s.fixed.currency == "USD" for s in schedules)
    settlement_text = (POLICIES / "settlement_policy.md").read_text()
    [listed] = re.findall(r"^Bank holidays: (.+)$", settlement_text, re.M)
    october = {h for h in holidays if (h.year, h.month) == (2026, 10)}
    assert october == {date.fromisoformat(d) for d in listed.split(", ")}
    year_config = yaml.safe_load(SCALE_CONFIG.read_text())
    assert years == {2026}
    assert holidays == {date.fromisoformat(d) for d in year_config["holidays"]}
    assert (year_config["period"]["start"], year_config["period"]["end"]) == (
        "2026-01-01",
        "2026-10-31",
    )


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"holidays": ["2026-13-01"]}, "holidays"),
        ({"fee_schedules": [{"gateway": "gateway_a", "rate_bps": 2.9}]}, "fee_schedules"),
        ({"extra": 1}, "extra"),
        ({"calendar_years": [2025]}, "holidays outside calendar_years: 2026-02-11"),
    ],
)
def test_a_malformed_reference_file_is_rejected(
    tmp_path: Path, change: dict[str, object], error: str
) -> None:
    content = json.loads(REFERENCE_FILE.read_text()) | change
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(content))

    with pytest.raises(ValueError, match=error):
        read_reference_file(path)


def test_an_unknown_anomaly_type_is_named_in_the_error(tmp_path: Path) -> None:
    path = tmp_path / "ground_truth.json"
    path.write_text(json.dumps({"anomalies": [{"type": "teleported_money"}], "expected_links": []}))

    with pytest.raises(ValueError, match="unknown anomaly type 'teleported_money'"):
        read_ground_truth(path)
