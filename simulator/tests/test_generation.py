import hashlib
import json
import re
import tomllib
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import CONFIGS, DEFAULT_CONFIG, raw_default, run
from simulator.checks import explain, find_violations, validate_files
from simulator.cli import main
from simulator.config import ANOMALY_TYPES, ConfigError, parse_config
from simulator.sim import count_for

RECORD_FILES = (
    "orders",
    "payments",
    "fees",
    "refunds",
    "authorizations",
    "settlements",
    "bank_transactions",
)


def _manifest(out: Path) -> dict[str, object]:
    manifest: dict[str, object] = json.loads((out / "manifest.json").read_text())
    return manifest


def test_cli_writes_every_output_and_the_manifest_hashes_them(anomalous_run: Path) -> None:
    expected = {f"{name}.{ext}" for name in RECORD_FILES for ext in ("csv", "json")} | {
        "policies/fee_schedule.md",
        "policies/refund_authorization.md",
        "policies/settlement_policy.md",
        "ground_truth.json",
    }
    manifest = _manifest(anomalous_run)
    files = manifest["files"]
    assert isinstance(files, dict)
    assert set(files) == expected
    for path, digest in files.items():
        assert hashlib.sha256((anomalous_run / path).read_bytes()).hexdigest() == digest
    assert manifest["seed"] == 42
    assert manifest["simulator_version"] == "0.1.0"


def test_same_seed_and_config_give_byte_identical_files(
    anomalous_run: Path, tmp_path: Path
) -> None:
    again = run(tmp_path, raw_default())
    assert (again / "manifest.json").read_bytes() == (anomalous_run / "manifest.json").read_bytes()


def test_different_seed_gives_different_data(anomalous_run: Path, tmp_path: Path) -> None:
    other = run(tmp_path, raw_default(), seed=43)
    first, second = _manifest(anomalous_run)["files"], _manifest(other)["files"]
    assert isinstance(first, dict) and isinstance(second, dict)
    assert first["orders.json"] != second["orders.json"]


def test_record_counts_follow_the_config(clean_run: Path) -> None:
    orders = json.loads((clean_run / "orders.json").read_text())["records"]
    payments = json.loads((clean_run / "payments.json").read_text())["records"]
    refunds = json.loads((clean_run / "refunds.json").read_text())["records"]
    authorizations = json.loads((clean_run / "authorizations.json").read_text())["records"]
    assert len(orders) == len(payments) == 200
    assert len(refunds) == len(authorizations) == 16  # refund_rate 0.08 of 200
    ground_truth = json.loads((clean_run / "ground_truth.json").read_text())
    assert ground_truth["anomalies"] == []
    assert len(ground_truth["expected_links"]) == 200


def test_every_anomaly_type_appears_at_least_twice_in_200_orders(anomalous_run: Path) -> None:
    ground_truth = json.loads((anomalous_run / "ground_truth.json").read_text())
    counts = Counter(a["type"] for a in ground_truth["anomalies"])
    assert set(counts) == set(ANOMALY_TYPES)
    assert min(counts.values()) >= 2
    subtypes = {
        a["subtype"] for a in ground_truth["anomalies"] if a["type"] == "missing_transaction"
    }
    assert subtypes == {"missing_in_orders", "missing_in_bank", "missing_in_gateway"}


def test_no_record_belongs_to_two_anomalies(anomalous_run: Path) -> None:
    ground_truth = json.loads((anomalous_run / "ground_truth.json").read_text())
    refs = [
        (r["source"], r["external_id"]) for a in ground_truth["anomalies"] for r in a["records"]
    ]
    assert len(refs) == len(set(refs))


def test_monetary_values_are_exported_as_decimal_strings(anomalous_run: Path) -> None:
    for name in RECORD_FILES:
        for record in json.loads((anomalous_run / f"{name}.json").read_text())["records"]:
            assert all(isinstance(value, str) for value in record.values())


def test_config_rejects_float_money() -> None:
    raw = raw_default()
    raw["gateways"]["gateway_a"]["fixed_fee"] = 0.3
    with pytest.raises(ConfigError, match="quoted decimal string"):
        parse_config(raw)


def test_config_rejects_unknown_anomaly_type() -> None:
    raw = raw_default()
    raw["anomaly_rates"]["made_up"] = "0.01"
    with pytest.raises(ConfigError, match="unknown anomaly types: made_up"):
        parse_config(raw)


def test_config_reads_holidays_sorted_and_keeps_them_in_the_resolved_config() -> None:
    raw = raw_default()
    raw["holidays"] = ["2026-10-20", "2026-10-09"]
    config = parse_config(raw)
    assert config.holidays == (date(2026, 10, 9), date(2026, 10, 20))
    assert config.to_dict()["holidays"] == ["2026-10-09", "2026-10-20"]


def test_config_with_no_holidays_or_an_empty_key_has_none() -> None:
    raw = raw_default()
    del raw["holidays"]
    assert parse_config(raw).holidays == ()
    raw["holidays"] = None
    assert parse_config(raw).holidays == ()


def test_a_run_without_holidays_publishes_none_and_verifies(tmp_path: Path) -> None:
    raw = raw_default()
    del raw["holidays"]
    raw["anomaly_rates"] = {}
    out = run(tmp_path, raw)
    policy = (out / "policies" / "settlement_policy.md").read_text()
    assert "Bank holidays: none\n" in policy
    assert json.loads((out / "manifest.json").read_text())["config"]["holidays"] == []
    assert find_violations(out) == []


def test_config_rejects_an_invalid_holiday() -> None:
    raw = raw_default()
    raw["holidays"] = ["2026-13-01"]
    with pytest.raises(ConfigError, match="holidays"):
        parse_config(raw)


def test_default_config_is_the_documented_200_order_run() -> None:
    assert yaml.safe_load(DEFAULT_CONFIG.read_text())["orders"] == 200


def test_anomaly_rates_apply_to_their_target_population(tmp_path: Path) -> None:
    raw = raw_default()
    raw["orders"] = 1000
    out = run(tmp_path, raw)
    settlements = len(json.loads((out / "settlements.json").read_text())["records"])
    ground_truth = json.loads((out / "ground_truth.json").read_text())
    counts = Counter(a["subtype"] or a["type"] for a in ground_truth["anomalies"])
    assert counts["delayed_settlement"] == count_for(Decimal("0.04"), settlements)
    assert counts["incorrect_amount"] == count_for(Decimal("0.04"), settlements)
    assert counts["missing_in_bank"] == count_for(Decimal("0.01"), settlements)
    assert counts["missing_in_orders"] == counts["missing_in_gateway"] == 10
    assert counts["duplicate_payment"] == 10


# Assumption, pending the owner's N (ADR-0015 point 4): at least 5 instances per batch type.
MIN_BATCH_INSTANCES = 5


def test_the_2000_order_run_is_ten_months_of_history_with_enough_batch_instances(
    tmp_path: Path,
) -> None:
    raw: dict[str, Any] = yaml.safe_load((CONFIGS / "orders-2000.yaml").read_text())
    config = parse_config(raw)
    assert (config.period_start, config.period_end) == (date(2026, 1, 1), date(2026, 10, 31))
    assert all(config.period_start <= h <= config.period_end for h in config.holidays)
    out = run(tmp_path, raw)
    anomalies = json.loads((out / "ground_truth.json").read_text())["anomalies"]
    counts = Counter(a["subtype"] or a["type"] for a in anomalies)
    for batch_type in ("delayed_settlement", "incorrect_amount", "missing_in_bank"):
        assert counts[batch_type] >= MIN_BATCH_INSTANCES, (batch_type, counts[batch_type])
    assert explain(out) == []


def test_committed_sample_is_the_seed_42_default_run(anomalous_run: Path) -> None:
    sample = Path(__file__).parents[1] / "samples" / "orders-200-seed-42"
    assert (sample / "manifest.json").read_bytes() == (anomalous_run / "manifest.json").read_bytes()
    assert validate_files(sample) == []


def test_simulator_depends_on_no_backend_langgraph_or_llm_package() -> None:
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    names = {re.split(r"[<>=\[ ]", d)[0].lower() for d in pyproject["project"]["dependencies"]}
    assert names == {"faker", "jsonschema", "pyyaml"}


def test_cli_exits_2_and_writes_nothing_on_an_invalid_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("orders: 0\n")
    out = tmp_path / "out"
    assert main(["--config", str(config), "--seed", "1", "--out", str(out)]) == 2
    assert "simulate: error:" in capsys.readouterr().err
    assert not out.exists()
