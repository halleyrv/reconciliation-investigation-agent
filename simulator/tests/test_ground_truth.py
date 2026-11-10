import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from conftest import raw_default, run
from simulator.business_days import add_business_days
from simulator.checks import find_violations
from simulator.config import parse_config
from simulator.sim import Sim


def _load(out: Path) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, Any]]:
    ids = {
        "orders": "order_id",
        "payments": "payment_id",
        "fees": "fee_id",
        "refunds": "refund_id",
        "settlements": "settlement_id",
        "bank_transactions": "bank_transaction_id",
    }
    data = {
        t: {r[k]: r for r in json.loads((out / f"{t}.json").read_text())["records"]}
        for t, k in ids.items()
    }
    return data, json.loads((out / "ground_truth.json").read_text())


def _settlement_of(data: dict[str, dict[str, dict[str, Any]]], source: str, ref: str) -> str:
    return str(data[source][ref]["settlement_ref"])


def _no_anomaly_inside_an_anomalous_batch(out: Path) -> None:
    data, ground_truth = _load(out)
    batch_anomalies = {"delayed_settlement", "incorrect_amount", "missing_in_bank"}
    anomalous_batches = {
        r["external_id"]
        for a in ground_truth["anomalies"]
        if (a["subtype"] or a["type"]) in batch_anomalies
        for r in a["records"]
        if r["source"] == "settlements"
    }
    claimed_orders = {
        r["external_id"]
        for a in ground_truth["anomalies"]
        for r in a["records"]
        if r["source"] == "orders"
    }
    for a in ground_truth["anomalies"]:
        for r in a["records"]:
            if r["source"] in {"payments", "refunds", "fees"}:
                batch = _settlement_of(data, r["source"], r["external_id"])
                assert batch not in anomalous_batches, (a["anomaly_id"], r)
    for payment in data["payments"].values():
        if payment["order_ref"] in claimed_orders:
            assert payment["settlement_ref"] not in anomalous_batches, payment


def test_no_record_of_an_anomaly_sits_in_an_anomalous_settlement_batch(
    anomalous_run: Path, tmp_path: Path
) -> None:
    _no_anomaly_inside_an_anomalous_batch(anomalous_run)
    raw = raw_default()
    raw["orders"] = 2000
    _no_anomaly_inside_an_anomalous_batch(run(tmp_path, raw))


def test_expected_delta_is_actual_minus_expected_for_every_anomaly_type(
    anomalous_run: Path,
) -> None:
    data, ground_truth = _load(anomalous_run)
    config = parse_config(json.loads((anomalous_run / "manifest.json").read_text())["config"])

    def amount(source: str, ref: str, field: str = "amount") -> Decimal:
        return Decimal(data[source][ref][field])

    for a in ground_truth["anomalies"]:
        refs: dict[str, list[str]] = {}
        for r in a["records"]:
            refs.setdefault(r["source"], []).append(r["external_id"])
        match a["subtype"] or a["type"]:
            case "duplicate_payment":
                expected = amount("payments", refs["payments"][1])
            case "unauthorized_refund":
                expected = -amount("refunds", refs["refunds"][0])
            case "incorrect_fee":
                payment = data["payments"][refs["payments"][0]]
                schedule = config.gateways[payment["gateway"]]
                fee = Decimal(payment["amount"]) * schedule.percentage_bps / 10_000
                due = (fee + schedule.fixed_fee).quantize(Decimal("0.01"), "ROUND_HALF_EVEN")
                expected = amount("fees", refs["fees"][0]) - due
            case "missing_in_orders":
                expected = amount("payments", refs["payments"][0])
            case "missing_in_bank":
                expected = -amount("settlements", refs["settlements"][0], "net_amount")
            case "missing_in_gateway":
                expected = amount("bank_transactions", refs["bank_transactions"][0])
            case "partial_payment":
                order_total = amount("orders", refs["orders"][0], "total_amount")
                expected = amount("payments", refs["payments"][0]) - order_total
            case "incorrect_amount":
                net = amount("settlements", refs["settlements"][0], "net_amount")
                expected = amount("bank_transactions", refs["bank_transactions"][0]) - net
            case "duplicate_refund":
                expected = -amount("refunds", refs["refunds"][1])
            case _:
                expected = Decimal("0.00")
        assert Decimal(a["expected_delta"]) == expected, a
        assert expected != 0 or a["type"] in {
            "delayed_settlement",
            "inconsistent_reference",
            "out_of_order_event",
            "conflicting_resent_record",
        }


def test_expected_links_are_consistent_chains_untouched_by_anomalies(anomalous_run: Path) -> None:
    data, ground_truth = _load(anomalous_run)
    anomalous = {
        (r["source"], r["external_id"]) for a in ground_truth["anomalies"] for r in a["records"]
    }
    links = ground_truth["expected_links"]
    assert len(links) > 150
    for link in links:
        payment = data["payments"][link["payment_id"]]
        credit = data["bank_transactions"][link["bank_transaction_id"]]
        assert payment["order_ref"] == link["order_id"]
        assert payment["settlement_ref"] == link["settlement_id"]
        assert link["settlement_id"] in credit["description"].split()
        for source, key in (
            ("orders", "order_id"),
            ("payments", "payment_id"),
            ("settlements", "settlement_id"),
            ("bank_transactions", "bank_transaction_id"),
        ):
            assert (source, link[key]) not in anomalous
    linked = {link["order_id"] for link in links}
    assert len(linked) == len(links)


def test_fee_rounds_once_half_even_on_a_half_cent_tie() -> None:
    sim = Sim(parse_config(raw_default()), seed=0)
    # gateway_b: 10.20 x 250 bps = 0.255, plus 0.25 = 0.505 -> 0.50 (half-up would give 0.51)
    assert sim.fee_for("gateway_b", Decimal("10.20")) == Decimal("0.50")
    assert sim.fee_for("gateway_b", Decimal("10.60")) == Decimal("0.52")  # 0.515 -> 0.52


def test_checker_applies_half_even_to_a_fee_on_a_tie(clean_run: Path, tmp_path: Path) -> None:
    import shutil

    for fee, flagged in (("0.50", False), ("0.51", True)):
        out = tmp_path / fee
        shutil.copytree(clean_run, out)
        payments = json.loads((out / "payments.json").read_text())
        fees = json.loads((out / "fees.json").read_text())
        payment = next(p for p in payments["records"] if p["gateway"] == "gateway_b")
        payment["amount"] = "10.20"
        next(f for f in fees["records"] if f["payment_ref"] == payment["payment_id"])["amount"] = (
            fee
        )
        (out / "payments.json").write_text(json.dumps(payments))
        (out / "fees.json").write_text(json.dumps(fees))
        i4 = [v for v in find_violations(out) if v.invariant == "I4"]
        assert bool(i4) is flagged


def test_settlement_lag_skips_weekends() -> None:
    no_holidays: frozenset[date] = frozenset()
    assert add_business_days(date(2026, 10, 2), 2, no_holidays) == date(2026, 10, 6)  # Fri -> Tue
    assert add_business_days(date(2026, 10, 3), 2, no_holidays) == date(2026, 10, 6)  # Sat -> Tue
    assert add_business_days(date(2026, 10, 5), 2, no_holidays) == date(2026, 10, 7)  # Mon -> Wed


def test_settlement_lag_skips_configured_holidays() -> None:
    holidays = frozenset({date(2026, 10, 9)})
    # Thursday batch, Friday is a holiday: Monday and Tuesday are the two business days.
    assert add_business_days(date(2026, 10, 8), 2, holidays) == date(2026, 10, 13)


def test_default_config_lists_fictional_holidays_inside_its_period() -> None:
    config = parse_config(raw_default())
    assert 2 <= len(config.holidays) <= 3
    assert all(config.period_start <= h <= config.period_end for h in config.holidays)


def test_a_batch_before_a_default_holiday_is_paid_one_business_day_later(clean_run: Path) -> None:
    data, _ = _load(clean_run)
    paid_on = {
        b["description"].split()[2]: b["value_date"] for b in data["bank_transactions"].values()
    }
    # 2026-10-09 is a default holiday: without it, a 2026-10-08 batch would be paid 2026-10-12.
    thursday = [s for s in data["settlements"].values() if s["batch_date"] == "2026-10-08"]
    assert thursday
    assert {paid_on[s["settlement_id"]] for s in thursday} == {"2026-10-13"}


def test_a_late_refund_with_no_later_batch_to_absorb_it_still_generates(tmp_path: Path) -> None:
    # Seed 285 used to fail: "no settlement batch can absorb RFD-000018".
    from simulator.checks import explain, validate_files

    out = run(tmp_path, raw_default(), seed=285)
    assert validate_files(out) == []
    assert explain(out) == []
