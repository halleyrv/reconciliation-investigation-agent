"""The simulator's ``ground_truth.json``. Read only by the evaluation command (AS1)."""

import json
from pathlib import Path

from recon.reconciliation.application.evaluation import Finding, Link
from recon.reconciliation.domain.results import DiscrepancyType
from recon.shared_kernel.money import parse_minor_units

# Phase 1 anomaly names -> detection catalog codes (assumption B2). Only this module knows them.
_CODE = {
    "duplicate_payment": "duplicate_payment",
    "unauthorized_refund": "unauthorized_refund",
    "incorrect_fee": "fee_mismatch",
    "partial_payment": "underpayment",
    "delayed_settlement": "settlement_delayed",
    "incorrect_amount": "amount_mismatch",
    "inconsistent_reference": "reference_mismatch",
    "out_of_order_event": "sequence_violation",
    "duplicate_refund": "duplicate_refund",
    "conflicting_resent_record": "source_conflict",
}


def _code(anomaly: dict[str, str]) -> str:
    if anomaly["type"] == "missing_transaction":
        code = anomaly["subtype"]  # missing_in_orders, missing_in_gateway, missing_in_bank
    else:
        code = _CODE.get(anomaly["type"], "")
    if code not in DiscrepancyType.__members__.values():
        raise ValueError(f"unknown anomaly type {anomaly['type']!r} / {anomaly['subtype']!r}")
    return code


def _signed_minor(text: str) -> int:
    return -parse_minor_units(text[1:]) if text.startswith("-") else parse_minor_units(text)


def read_ground_truth(path: Path) -> tuple[list[Finding], set[Link]]:
    """Raises ``ValueError`` (or ``KeyError``) when the file is not a ground truth."""
    data = json.loads(path.read_text(encoding="utf-8"))
    findings = [
        Finding(
            _code(a),
            frozenset((r["source"], r["external_id"]) for r in a["records"]),
            _signed_minor(a["expected_delta"]),
        )
        for a in data["anomalies"]
    ]
    links = {
        Link(x["order_id"], x["payment_id"], x["settlement_id"], x["bank_transaction_id"])
        for x in data["expected_links"]
    }
    return findings, links
