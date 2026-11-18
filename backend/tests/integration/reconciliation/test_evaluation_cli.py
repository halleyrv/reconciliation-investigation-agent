"""AC-2b.2, AC-2b.4 and AC-2b.6 through the operator commands, as the backend README lists them."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from recon.bootstrap.cli import evaluate_main, main, reconcile_main, reference_main
from recon.bootstrap.migrations import upgrade
from tests.integration.conftest import SAMPLE, create_database, drop_database

REFERENCE_FILE = Path(__file__).parents[3] / "reference" / "gateway-policy-2026.json"
OCTOBER = ["--from", "2026-10-01", "--to", "2026-10-31"]


@pytest.fixture
def database(migrated_url: str, engine: object, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("RECON_DATABASE_URL", migrated_url)
    return migrated_url


def _reconcile_sample(sample: Path) -> None:
    assert main([str(sample)]) == 0
    assert reference_main([str(REFERENCE_FILE)]) == 0
    assert reconcile_main(OCTOBER) == 0


def test_the_sample_scores_100_percent_per_type_with_every_delta_equal(
    database: str, sample: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _reconcile_sample(sample)
    capsys.readouterr()
    report = tmp_path / "report.md"

    assert evaluate_main([str(sample), *OCTOBER, "--report", str(report)]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "discrepancies: 41 expected, 41 detected, 41 matched",
        "links: 158 expected, 158 found, 158 matched",
        "delta mismatches: 0",
        f"report: {report} (PASS)",
    ]
    text_ = report.read_text()
    assert "- Result: **PASS**" in text_
    type_rows = [line for line in text_.splitlines() if line.startswith("| `")]
    assert len(type_rows) == 13  # every catalog code occurs in the seed-42 ground truth
    assert all(line.endswith("| 100.0% | 100.0% |") for line in type_rows)
    assert "| 158 | 158 | 158 | 100.0% | 100.0% |" in text_


def test_a_miss_is_listed_and_exits_1(
    database: str, sample: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _reconcile_sample(sample)
    truth = sample / "ground_truth.json"
    data = json.loads(truth.read_text())
    anomaly = next(a for a in data["anomalies"] if a["type"] == "incorrect_fee")
    anomaly["expected_delta"] = "9.99"
    data["anomalies"].append(
        {**anomaly, "anomaly_id": "ANM-9999", "records": [{"source": "fees", "external_id": "X"}]}
    )
    truth.write_text(json.dumps(data))
    report = tmp_path / "report.md"

    assert evaluate_main([str(sample), *OCTOBER, "--report", str(report)]) == 1

    out = capsys.readouterr().out
    assert "delta mismatches: 1" in out and "(FAIL)" in out
    text_ = report.read_text()
    assert "- `fee_mismatch` delta 999: fees/X" in text_
    assert "| `fee_mismatch` | 5 | 4 | 4 | 100.0% | 80.0% |" in text_


def test_evaluating_a_period_never_reconciled_exits_2(
    database: str, sample: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "report.md"

    assert evaluate_main([str(sample), *OCTOBER, "--report", str(report)]) == 2
    assert reconcile_main(["--from", "2026-10-31", "--to", "2026-10-01"]) == 2

    err = capsys.readouterr().err
    assert "recon-evaluate: nothing evaluated: no completed v1 run" in err
    assert "recon-reconcile: nothing run: period ends (2026-10-01) before it starts" in err
    assert not report.exists()


def test_two_fresh_databases_produce_identical_fingerprints_and_deltas(
    sample: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = []
    for _ in range(2):
        url = create_database()
        engine = create_engine(url)
        try:
            upgrade(url)
            monkeypatch.setenv("RECON_DATABASE_URL", url)
            _reconcile_sample(sample)
            with engine.connect() as connection:
                rows = connection.execute(
                    text("SELECT fingerprint, type, delta_minor FROM recon.discrepancies")
                )
                outputs.append(sorted(tuple(r) for r in rows))
        finally:
            engine.dispose()
            drop_database(url)

    assert len(outputs[0]) == 41
    assert outputs[0] == outputs[1]


def test_october_is_refused_until_its_last_payouts_are_imported(
    database: str, sample: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bank = sample / "bank_transactions.json"
    data = json.loads(bank.read_text())
    data["records"] = [r for r in data["records"] if r["value_date"] <= "2026-10-31"]
    bank.write_text(json.dumps(data))
    manifest = json.loads((sample / "manifest.json").read_text())
    manifest["files"]["bank_transactions.json"] = hashlib.sha256(bank.read_bytes()).hexdigest()
    (sample / "manifest.json").write_text(json.dumps(manifest))
    assert main([str(sample)]) == 0
    assert reference_main([str(REFERENCE_FILE)]) == 0

    assert reconcile_main(OCTOBER) == 2

    err = capsys.readouterr().err
    assert "is not closed: bank data reaches 2026-10-30, its last payouts are due 2026-11-03" in err


def _export_bank(sample: Path, keep: Callable[[str], bool]) -> None:
    """Rewrite the export so it holds only the bank statement lines whose value date is kept."""
    bank = sample / "bank_transactions.json"
    data = json.loads((SAMPLE / "bank_transactions.json").read_text())
    data["records"] = [r for r in data["records"] if keep(r["value_date"])]
    bank.write_text(json.dumps(data))
    manifest = json.loads((sample / "manifest.json").read_text())
    manifest["files"]["bank_transactions.json"] = hashlib.sha256(bank.read_bytes()).hexdigest()
    (sample / "manifest.json").write_text(json.dumps(manifest))


def test_october_stays_open_while_a_gap_between_bank_statements_is_not_imported(
    database: str, sample: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert reference_main([str(REFERENCE_FILE)]) == 0
    _export_bank(sample, lambda day: day <= "2026-10-15")
    assert main([str(sample)]) == 0
    _export_bank(sample, lambda day: day >= "2026-10-21")  # 16th and 19th missing
    assert main([str(sample)]) == 0

    assert reconcile_main(OCTOBER) == 2
    err = capsys.readouterr().err
    assert "is not closed: bank data reaches 2026-10-15, its last payouts are due 2026-11-03" in err

    _export_bank(sample, lambda day: True)  # the full statement brings the missing days
    assert main([str(sample)]) == 0
    assert reconcile_main(OCTOBER) == 0
