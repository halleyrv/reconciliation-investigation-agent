"""Data validation of a generated run, read back from its files.

- `find_violations`: internal consistency invariants I1-I10 (phase 1 amendments).
- `explain`: every violation is explained by exactly one ground-truth anomaly, and every
  anomaly breaks exactly the invariants it declares.
- `validate_files`: JSON Schemas, CSV dialect (ADR-0014), CSV equals JSON, manifest hashes.
"""

import codecs
import csv
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from simulator.business_days import add_business_days
from simulator.config import Config, parse_config
from simulator.records import RECORD_TYPES

type RecordRef = tuple[str, str]
type Row = dict[str, Any]

MONEY_FIELDS = {
    "orders": "total_amount",
    "payments": "amount",
    "fees": "amount",
    "refunds": "amount",
    "authorizations": "max_amount",
    "settlements": "net_amount",
    "bank_transactions": "amount",
}
MONEY_PATTERN = re.compile(r"^[0-9]+\.[0-9]{2}$")
SETTLEMENT_REF = re.compile(r"\bSTL-[0-9]{6}\b")
FEE_ROW = re.compile(r"^\| (\S+) \| ([0-9]+) \| ([0-9.]+) \|$", re.MULTILINE)
LAG_LINE = re.compile(r"^Settlement lag: ([0-9]+) business days$", re.MULTILINE)
HOLIDAYS_LINE = re.compile(r"^Bank holidays: (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Violation:
    invariant: str
    records: tuple[RecordRef, ...]
    detail: str


def _id_field(record_type: str) -> str:
    return fields(RECORD_TYPES[record_type])[0].name


def _amount(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class _Run:
    """The records of one run, indexed by external ID (the last row wins on duplicates)."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.rows: dict[str, list[Row]] = {
            t: _read_json(out / f"{t}.json")["records"] for t in RECORD_TYPES
        }
        self.by_id: dict[str, dict[str, Row]] = {
            t: {r[_id_field(t)]: r for r in rows} for t, rows in self.rows.items()
        }
        self.config: Config = parse_config(_read_json(out / "manifest.json")["config"])

    def ref(self, record_type: str, row: Row) -> RecordRef:
        return record_type, str(row[_id_field(record_type)])

    def grouped(self, record_type: str, key: str) -> dict[str, list[Row]]:
        groups: dict[str, list[Row]] = defaultdict(list)
        for row in self.rows[record_type]:
            groups[row[key]].append(row)
        return groups


def _total(rows: list[Row]) -> Decimal:
    return sum((_amount(r["amount"]) or Decimal(0) for r in rows), Decimal(0))


def _i1(run: _Run) -> list[Violation]:
    orders, found = run.by_id["orders"], []
    for p in run.rows["payments"]:
        order = orders.get(p["order_ref"])
        if order is None:
            found.append(Violation("I1", (run.ref("payments", p),), "payment for unknown order"))
            continue
        paid, total = _amount(p["amount"]), _amount(order["total_amount"])
        if paid != total:
            refs = (run.ref("orders", order), run.ref("payments", p))
            found.append(Violation("I1", refs, f"payment {paid}, order total {total}"))
    return found


def _i2(run: _Run) -> list[Violation]:
    payments, found = run.by_id["payments"], []
    for r in run.rows["refunds"]:
        if r["payment_ref"] not in payments:
            found.append(Violation("I2", (run.ref("refunds", r),), "refund of unknown payment"))
    for payment_id, refunds in run.grouped("refunds", "payment_ref").items():
        payment = payments.get(payment_id)
        if payment is None:
            continue
        refunded, amount = _total(refunds), _amount(payment["amount"]) or Decimal(0)
        if refunded > amount:
            refs = (("payments", payment_id), *(run.ref("refunds", r) for r in refunds))
            found.append(Violation("I2", refs, f"refunded {refunded} of {amount}"))
    return found


def _i3(run: _Run) -> list[Violation]:
    by_subject = run.grouped("authorizations", "subject_ref")
    found = []
    for r in run.rows["refunds"]:
        authorizations = [
            a for a in by_subject.get(r["refund_id"], []) if a["subject_kind"] == "refund"
        ]
        amount = _amount(r["amount"]) or Decimal(0)
        covered = any(
            (_amount(a["max_amount"]) or Decimal(0)) >= amount
            and _instant(a["approved_at"]) < _instant(r["refunded_at"])
            for a in authorizations
        )
        if not covered:
            refs = (run.ref("refunds", r), *(run.ref("authorizations", a) for a in authorizations))
            detail = "no authorization" if not authorizations else "authorization does not cover it"
            found.append(Violation("I3", refs, detail))
    return found


def _i4(run: _Run) -> list[Violation]:
    payments, gateways, found = run.by_id["payments"], run.config.gateways, []
    fees_by_payment = run.grouped("fees", "payment_ref")
    for f in run.rows["fees"]:
        payment = payments.get(f["payment_ref"])
        if payment is None:
            found.append(Violation("I4", (run.ref("fees", f),), "fee for unknown payment"))
            continue
        schedule = gateways.get(payment["gateway"])
        amount = _amount(payment["amount"])
        if schedule is None or amount is None:
            found.append(Violation("I4", (run.ref("fees", f),), "no fee schedule applies"))
            continue
        # Rounded here on purpose, not with the generator's helper: an independent check.
        expected = (
            amount * schedule.percentage_bps / Decimal(10_000) + schedule.fixed_fee
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if _amount(f["amount"]) != expected:
            refs = (run.ref("payments", payment), run.ref("fees", f))
            found.append(Violation("I4", refs, f"fee {f['amount']}, schedule gives {expected}"))
    for payment_id in payments:
        count = len(fees_by_payment.get(payment_id, []))
        if count != 1:
            found.append(Violation("I4", (("payments", payment_id),), f"{count} fees"))
    return found


def _i5(run: _Run) -> list[Violation]:
    settlements, found = run.by_id["settlements"], []
    net: dict[str, Decimal] = defaultdict(Decimal)
    for record_type, sign in (("payments", 1), ("refunds", -1), ("fees", -1)):
        for row in run.rows[record_type]:
            if row["settlement_ref"] not in settlements:
                found.append(Violation("I5", (run.ref(record_type, row),), "unknown settlement"))
            else:
                net[row["settlement_ref"]] += sign * (_amount(row["amount"]) or Decimal(0))
    credits: dict[str, list[Row]] = defaultdict(list)
    for b in run.rows["bank_transactions"]:
        match = SETTLEMENT_REF.search(b["description"])
        if match is None or match.group() not in settlements:
            found.append(Violation("I5", (run.ref("bank_transactions", b),), "no settlement"))
        else:
            credits[match.group()].append(b)
    lag = run.config.settlement_lag_business_days
    for settlement_id, s in settlements.items():
        ref = ("settlements", settlement_id)
        stated = _amount(s["net_amount"])
        if net[settlement_id] != stated:
            found.append(
                Violation("I5", (ref,), f"members net {net[settlement_id]}, says {stated}")
            )
        paid = credits.get(settlement_id, [])
        if len(paid) != 1:
            refs = (ref, *(run.ref("bank_transactions", b) for b in paid))
            found.append(Violation("I5", refs, f"{len(paid)} bank credits"))
            continue
        credit = paid[0]
        due = add_business_days(date.fromisoformat(s["batch_date"]), lag, run.config.holidays)
        if (
            _amount(credit["amount"]) != stated
            or credit["direction"] != "credit"
            or date.fromisoformat(credit["value_date"]) != due
        ):
            refs = (ref, run.ref("bank_transactions", credit))
            found.append(Violation("I5", refs, f"credit differs: due {due} for {stated}"))
    return found


def _i6(run: _Run) -> list[Violation]:
    orders, payments, settlements = (run.by_id[t] for t in ("orders", "payments", "settlements"))
    found = []
    for p in run.rows["payments"]:
        order = orders.get(p["order_ref"])
        if order is not None and _instant(order["placed_at"]) > _instant(p["captured_at"]):
            refs = (run.ref("orders", order), run.ref("payments", p))
            found.append(Violation("I6", refs, "payment captured before the order was placed"))
        s = settlements.get(p["settlement_ref"])
        if s is not None and _instant(p["captured_at"]).date() > date.fromisoformat(
            s["batch_date"]
        ):
            refs = (run.ref("payments", p), run.ref("settlements", s))
            found.append(Violation("I6", refs, "payment after its settlement batch"))
    for b in run.rows["bank_transactions"]:
        match = SETTLEMENT_REF.search(b["description"])
        s = settlements.get(match.group()) if match else None
        if s is not None and date.fromisoformat(b["value_date"]) < date.fromisoformat(
            s["batch_date"]
        ):
            refs = (run.ref("settlements", s), run.ref("bank_transactions", b))
            found.append(Violation("I6", refs, "bank credit before its settlement"))
    for r in run.rows["refunds"]:
        paid = payments.get(r["payment_ref"])
        if paid is not None and _instant(r["refunded_at"]) <= _instant(paid["captured_at"]):
            refs = (run.ref("payments", paid), run.ref("refunds", r))
            found.append(Violation("I6", refs, "refund not after its payment"))
    return found


def _i7(run: _Run) -> list[Violation]:
    found = []
    for record_type, rows in run.rows.items():
        seen: dict[str, int] = defaultdict(int)
        for row in rows:
            seen[row[_id_field(record_type)]] += 1
        for external_id, count in seen.items():
            if count > 1:
                found.append(
                    Violation(
                        "I7", ((record_type, external_id),), f"external ID sent {count} times"
                    )
                )
    return found


def _i8(run: _Run) -> list[Violation]:
    found = []
    for record_type, field in MONEY_FIELDS.items():
        for row in run.rows[record_type]:
            value = row[field]
            if not (isinstance(value, str) and MONEY_PATTERN.match(value) and Decimal(value) > 0):
                found.append(
                    Violation("I8", (run.ref(record_type, row),), f"{field}={value!r} is invalid")
                )
    return found


def _i9(run: _Run) -> list[Violation]:
    policies = run.out / "policies"
    found = []
    fee_text = (policies / "fee_schedule.md").read_text(encoding="utf-8")
    stated = {name: (int(bps), Decimal(fixed)) for name, bps, fixed in FEE_ROW.findall(fee_text)}
    expected = {n: (g.percentage_bps, g.fixed_fee) for n, g in run.config.gateways.items()}
    if stated != expected:
        found.append(
            Violation("I9", (("policies", "fee_schedule.md"),), f"{stated} != config {expected}")
        )
    lag_text = (policies / "settlement_policy.md").read_text(encoding="utf-8")
    lag = LAG_LINE.search(lag_text)
    if lag is None or int(lag.group(1)) != run.config.settlement_lag_business_days:
        found.append(
            Violation("I9", (("policies", "settlement_policy.md"),), "settlement lag differs")
        )
    holidays = HOLIDAYS_LINE.search(lag_text)
    expected_holidays = ", ".join(h.isoformat() for h in run.config.holidays) or "none"
    if holidays is None or holidays.group(1) != expected_holidays:
        found.append(
            Violation("I9", (("policies", "settlement_policy.md"),), "bank holidays differ")
        )
    return found


def _i10(run: _Run) -> list[Violation]:
    """v1 scope (ADR-0012): exactly one payment per order; split payments are out of scope."""
    by_order, found = run.grouped("payments", "order_ref"), []
    for order_id in run.by_id["orders"]:
        payments = by_order.get(order_id, [])
        if len(payments) != 1:
            refs = (("orders", order_id), *(run.ref("payments", p) for p in payments))
            found.append(Violation("I10", refs, f"{len(payments)} payments"))
    return found


INVARIANTS = (_i1, _i2, _i3, _i4, _i5, _i6, _i7, _i8, _i9, _i10)


def find_violations(out: Path) -> list[Violation]:
    run = _Run(out)
    return [v for check in INVARIANTS for v in check(run)]


def explain(out: Path) -> list[str]:
    """Problems that stop the ground truth from explaining the run (empty means AC3 holds)."""
    violations = find_violations(out)
    anomalies = _read_json(out / "ground_truth.json")["anomalies"]
    refs = {
        a["anomaly_id"]: {(r["source"], r["external_id"]) for r in a["records"]} for a in anomalies
    }
    # Lists, not sets: an extra violation of a declared invariant must not hide (M-A).
    caused: dict[str, list[str]] = defaultdict(list)
    problems = []
    for v in violations:
        matches = [a for a in anomalies if refs[a["anomaly_id"]] & set(v.records)]
        if len(matches) != 1:
            who = "no anomaly" if not matches else f"{len(matches)} anomalies"
            problems.append(
                f"{v.invariant} violation on {list(v.records)} ({v.detail}) is explained by {who}"
            )
            continue
        anomaly = matches[0]
        caused[anomaly["anomaly_id"]].append(v.invariant)
        if v.invariant not in anomaly["invariants_broken"]:
            problems.append(f"{anomaly['anomaly_id']} breaks undeclared {v.invariant}: {v.detail}")
    for a in anomalies:
        broken = caused[a["anomaly_id"]]
        if not broken:
            problems.append(f"{a['anomaly_id']} ({a['type']}) causes no violation")
        elif sorted(broken) != sorted(a["invariants_broken"]):
            problems.append(
                f"{a['anomaly_id']} ({a['type']}) breaks {sorted(broken)}, "
                f"declares {a['invariants_broken']}"
            )
    return problems


def _schema(name: str) -> dict[str, Any]:
    text = files("simulator").joinpath("schemas", f"{name}.schema.json").read_text("utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


def validate_files(out: Path) -> list[str]:
    problems = []
    for path, digest in _read_json(out / "manifest.json")["files"].items():
        target = out / path
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            problems.append(f"{path}: missing or does not match its manifest hash")
    for record_type in RECORD_TYPES:
        schema = _schema(record_type)
        validator = Draft202012Validator(schema)
        document = _read_json(out / f"{record_type}.json")
        problems += [f"{record_type}.json: {e.message}" for e in validator.iter_errors(document)]
        raw = (out / f"{record_type}.csv").read_bytes()
        # CSV dialect of ADR-0014. No value holds a line break, so any CRLF is a line ending.
        if raw.startswith(codecs.BOM_UTF8) or b"\r\n" in raw or not raw.endswith(b"\n"):
            problems.append(f"{record_type}.csv: not UTF-8 without BOM with LF line endings")
        with (out / f"{record_type}.csv").open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            header = reader.fieldnames
        columns = list(schema["$defs"]["record"]["properties"])
        if header != columns:
            problems.append(f"{record_type}.csv: columns {header} differ from the schema")
        as_document = {**document, "records": rows}
        problems += [f"{record_type}.csv: {e.message}" for e in validator.iter_errors(as_document)]
        if rows != document["records"]:
            problems.append(f"{record_type}.csv differs from {record_type}.json")
    ground_truth = _read_json(out / "ground_truth.json")
    problems += [
        f"ground_truth.json: {e.message}"
        for e in Draft202012Validator(_schema("ground_truth")).iter_errors(ground_truth)
    ]
    return problems
