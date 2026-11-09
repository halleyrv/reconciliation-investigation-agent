import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
import yaml
from conftest import DEFAULT_CONFIG, raw_default, run
from simulator.config import ANOMALY_TYPES, ConfigError, parse_config

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


def test_default_config_is_the_documented_200_order_run() -> None:
    assert yaml.safe_load(DEFAULT_CONFIG.read_text())["orders"] == 200
