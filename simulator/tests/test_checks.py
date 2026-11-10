import codecs
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from simulator.checks import explain, find_violations, validate_files
from simulator.cli import verify_main
from simulator.export import columns, to_csv

type Records = dict[str, list[dict[str, Any]]]


def _copy(src: Path, tmp_path: Path) -> Path:
    dst = tmp_path / "run"
    shutil.copytree(src, dst)
    return dst


def _tamper(out: Path, record_type: str, change: Callable[[list[dict[str, Any]]], object]) -> None:
    path = out / f"{record_type}.json"
    data = json.loads(path.read_text())
    change(data["records"])
    path.write_text(json.dumps(data))


def _first_refunded_payment(out: Path) -> str:
    refunds = json.loads((out / "refunds.json").read_text())["records"]
    return str(refunds[0]["payment_ref"])


def test_clean_run_has_zero_invariant_violations(clean_run: Path) -> None:
    assert find_violations(clean_run) == []


def test_every_violation_is_explained_by_exactly_one_anomaly_and_vice_versa(
    anomalous_run: Path,
) -> None:
    assert find_violations(anomalous_run) != []
    assert explain(anomalous_run) == []


def test_clean_and_anomalous_runs_match_their_schemas_and_csv_equals_json(
    clean_run: Path, anomalous_run: Path
) -> None:
    assert validate_files(clean_run) == []
    assert validate_files(anomalous_run) == []


def _bump(field: str, delta: str = "1.00") -> Callable[[list[dict[str, Any]]], None]:
    from decimal import Decimal

    def change(records: list[dict[str, Any]]) -> None:
        records[0][field] = str(Decimal(records[0][field]) + Decimal(delta))

    return change


TAMPERS: list[tuple[str, str, Callable[[list[dict[str, Any]]], object]]] = [
    ("I1", "payments", _bump("amount")),
    ("I3", "authorizations", lambda rs: rs.pop(0)),
    ("I4", "fees", _bump("amount", "0.01")),
    ("I5", "bank_transactions", _bump("amount")),
    ("I6", "orders", lambda rs: rs[0].update(placed_at="2026-12-31T00:00:00Z")),
    ("I7", "orders", lambda rs: rs.append(dict(rs[0]))),
    ("I8", "authorizations", lambda rs: rs[0].update(max_amount="1.5")),
    ("I10", "payments", lambda rs: rs.append({**rs[0], "payment_id": "PAY-999999"})),
]


def test_a_second_full_payment_breaks_i10_and_not_i1(clean_run: Path, tmp_path: Path) -> None:
    out = _copy(clean_run, tmp_path)
    _tamper(out, "payments", lambda rs: rs.append({**rs[0], "payment_id": "PAY-999999"}))
    by_invariant = {v.invariant: v for v in find_violations(out) if v.invariant in {"I1", "I10"}}
    assert set(by_invariant) == {"I10"}
    assert ("payments", "PAY-999999") in by_invariant["I10"].records


def test_a_payment_below_its_order_total_breaks_i1_and_not_i10(
    clean_run: Path, tmp_path: Path
) -> None:
    out = _copy(clean_run, tmp_path)
    _tamper(out, "payments", _bump("amount", "-1.00"))
    assert {v.invariant for v in find_violations(out)} & {"I1", "I10"} == {"I1"}


def test_order_payment_anomalies_declare_the_invariants_of_adr_0012(anomalous_run: Path) -> None:
    ground_truth = json.loads((anomalous_run / "ground_truth.json").read_text())
    declared = {
        a["subtype"] or a["type"]: a["invariants_broken"]
        for a in ground_truth["anomalies"]
        if (a["subtype"] or a["type"])
        in {"duplicate_payment", "partial_payment", "missing_in_orders", "inconsistent_reference"}
    }
    assert declared == {
        "duplicate_payment": ["I10"],
        "partial_payment": ["I1"],
        "missing_in_orders": ["I1"],
        "inconsistent_reference": ["I1", "I10"],
    }


@pytest.mark.parametrize(("invariant", "record_type", "change"), TAMPERS)
def test_checker_detects_each_broken_invariant(
    clean_run: Path,
    tmp_path: Path,
    invariant: str,
    record_type: str,
    change: Callable[[list[dict[str, Any]]], object],
) -> None:
    out = _copy(clean_run, tmp_path)
    _tamper(out, record_type, change)
    assert invariant in {v.invariant for v in find_violations(out)}


def test_checker_detects_refunds_exceeding_their_payment(clean_run: Path, tmp_path: Path) -> None:
    out = _copy(clean_run, tmp_path)
    payment_ref = _first_refunded_payment(out)
    _tamper(out, "refunds", lambda rs: rs[0].update(amount="99999.00"))
    i2 = [v for v in find_violations(out) if v.invariant == "I2"]
    assert len(i2) == 1
    assert ("payments", payment_ref) in i2[0].records


def test_checker_detects_policy_numbers_that_differ_from_the_config(
    clean_run: Path, tmp_path: Path
) -> None:
    out = _copy(clean_run, tmp_path)
    policy = out / "policies" / "fee_schedule.md"
    policy.write_text(policy.read_text().replace("| gateway_a | 290 |", "| gateway_a | 300 |"))
    assert [v.invariant for v in find_violations(out)] == ["I9"]


def test_checker_detects_a_holiday_list_that_differs_from_the_config(
    clean_run: Path, tmp_path: Path
) -> None:
    out = _copy(clean_run, tmp_path)
    policy = out / "policies" / "settlement_policy.md"
    assert "2026-10-09" in policy.read_text()
    policy.write_text(policy.read_text().replace("2026-10-09", "2026-10-10"))
    assert [v.invariant for v in find_violations(out)] == ["I9"]


def test_explain_reports_violations_and_anomalies_that_do_not_match(
    clean_run: Path, tmp_path: Path
) -> None:
    out = _copy(clean_run, tmp_path)
    _tamper(out, "fees", _bump("amount", "0.01"))
    ground_truth = json.loads((out / "ground_truth.json").read_text())
    ground_truth["anomalies"] = [
        {
            "anomaly_id": "ANM-0001",
            "type": "partial_payment",
            "records": [{"source": "orders", "external_id": "ORD-000002"}],
            "invariants_broken": ["I1"],
        }
    ]
    (out / "ground_truth.json").write_text(json.dumps(ground_truth))
    problems = explain(out)
    assert any("I4" in p and "no anomaly" in p for p in problems)
    assert any("ANM-0001" in p and "no violation" in p for p in problems)


def test_validate_files_detects_csv_that_differs_from_json(clean_run: Path, tmp_path: Path) -> None:
    out = _copy(clean_run, tmp_path)
    csv_path = out / "orders.csv"
    lines = csv_path.read_text().splitlines(keepends=True)
    csv_path.write_text("".join([lines[0], *lines[2:]]))
    assert "orders.csv differs from orders.json" in validate_files(out)


@pytest.mark.parametrize(
    "damage",
    [
        lambda raw: codecs.BOM_UTF8 + raw,
        lambda raw: raw.replace(b"\n", b"\r\n"),
        lambda raw: raw.rstrip(b"\n"),
    ],
    ids=["bom", "crlf", "no-final-lf"],
)
def test_validate_files_detects_a_csv_outside_the_dialect(
    clean_run: Path, tmp_path: Path, damage: Callable[[bytes], bytes]
) -> None:
    out = _copy(clean_run, tmp_path)
    path = out / "orders.csv"
    path.write_bytes(damage(path.read_bytes()))
    assert "orders.csv: not UTF-8 without BOM with LF line endings" in validate_files(out)


def test_csv_quotes_only_values_with_a_comma_quote_or_line_break() -> None:
    row = {column: "x" for column in columns("orders")}
    row["customer_name"] = 'Doe, "Jo"'
    header, line, end = to_csv("orders", [row]).split("\n")
    assert header == ",".join(columns("orders"))
    assert line == ",".join(
        '"Doe, ""Jo"""' if column == "customer_name" else "x" for column in columns("orders")
    )
    assert end == ""


def test_validate_files_detects_schema_violations(clean_run: Path, tmp_path: Path) -> None:
    out = _copy(clean_run, tmp_path)
    _tamper(out, "payments", lambda rs: rs[0].update(amount=12.5))
    assert "payments.json: 12.5 is not of type 'string'" in validate_files(out)


def test_verify_command_passes_on_a_generated_run(
    anomalous_run: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert verify_main([str(anomalous_run)]) == 0
    assert "verification passed" in capsys.readouterr().out


def test_verify_command_fails_when_the_ground_truth_does_not_explain_the_data(
    clean_run: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _copy(clean_run, tmp_path)
    _tamper(out, "fees", _bump("amount", "0.01"))
    assert verify_main([str(out)]) == 1
    assert "I4" in capsys.readouterr().out
