"""Write a dataset to disk: CSV + JSON per record type, policies, ground truth, manifest."""

import csv
import hashlib
import io
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from simulator import __version__
from simulator.config import Config
from simulator.generator import Dataset
from simulator.records import RECORD_TYPES, to_row
from simulator.sim import REFUND_WINDOW_DAYS

RECORD_SCHEMA_VERSION = "1.0.0"
# No simulated record is a dispute: the policy is retrievable, but no case exercises it.
DISPUTE_RESPONSE_BUSINESS_DAYS = 7


def dumps(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def columns(record_type: str) -> list[str]:
    return [f.name for f in fields(RECORD_TYPES[record_type])]


def to_csv(record_type: str, rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns(record_type), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def policy_documents(config: Config) -> dict[str, str]:
    """Policy numbers come from the same config as the data (invariant I9)."""
    fee_rows = "\n".join(
        f"| {name} | {g.percentage_bps} | {g.fixed_fee} |"
        for name, g in sorted(config.gateways.items())
    )
    lag = config.settlement_lag_business_days
    holidays = ", ".join(h.isoformat() for h in config.holidays) or "none"
    return {
        "fee_schedule.md": (
            "# Gateway Fee Schedule\n\n"
            f"All fees are charged in {config.currency} on each captured payment: a percentage "
            "in basis points plus a fixed amount, rounded once to cents with ROUND_HALF_EVEN. "
            "Fees are not returned when a payment is refunded.\n\n"
            "| Gateway | Percentage (bps) | Fixed fee |\n"
            "|---------|------------------|-----------|\n"
            f"{fee_rows}\n"
        ),
        "refund_authorization.md": (
            "# Refund Authorization Policy\n\n"
            "Every refund requires an internal authorization record approved before the refund "
            "is issued. The authorized maximum amount must cover the refunded amount. "
            "One authorization covers exactly one refund.\n\n"
            "The total refunded for a payment never exceeds the captured amount.\n"
        ),
        "refund_limits.md": (
            "# Refund Limits Policy\n\n"
            "A refund is issued after its payment is captured and within the refund window "
            "counted in calendar days from the capture.\n\n"
            f"Refund window: {REFUND_WINDOW_DAYS} calendar days\n\n"
            f"A payment is refunded at most once, fully or partially, in {config.currency}. "
            "The refunded amount is at least 0.01 and never exceeds the captured amount of the "
            "payment. A second refund of the same payment is not allowed.\n\n"
            "A refund is netted in a later settlement batch of the gateway that captured the "
            "payment, never in the batch of the payment itself.\n"
        ),
        "settlement_policy.md": (
            "# Settlement and Cut-off Policy\n\n"
            "Each gateway settles one batch per calendar day (cut-off 23:59:59 UTC). A batch "
            "nets the day's captured payments minus the refunds it absorbs and the fees of its "
            "payments.\n\n"
            f"Settlement lag: {lag} business days\n\n"
            f"Bank holidays: {holidays}\n\n"
            "Each batch is paid out as exactly one bank credit, dated the batch date plus the "
            "settlement lag. Business days are Monday to Friday, except the bank holidays "
            "listed above.\n"
        ),
        "dispute_handling.md": (
            "# Dispute Handling Policy\n\n"
            "A dispute is a customer's challenge of a captured payment raised through the "
            "gateway. The merchant answers each dispute with its evidence (order, payment, "
            "refund and authorization records) within the response window, counted in "
            "business days from the day the gateway reports the dispute.\n\n"
            f"Response window: {DISPUTE_RESPONSE_BUSINESS_DAYS} business days\n\n"
            f"Bank holidays: {holidays}\n\n"
            "While a dispute is open, the disputed amount is not refunded a second time and "
            "no adjustment is booked for it. An unanswered dispute is lost by default.\n"
        ),
        "transaction_reconciliation.md": (
            "# Transaction Reconciliation Policy\n\n"
            "Reconciliation compares independent sources record by record: orders from the "
            "shop, payments, refunds, fees and settlement batches from the gateway, "
            "authorizations from the back office and credits from the bank statement.\n\n"
            "- Every order has exactly one captured payment, and the payment amount equals the "
            "order total.\n"
            "- Every refund has an approved authorization that covers its amount.\n"
            "- Every fee equals the gateway's fee schedule applied to its payment.\n"
            "- A settlement batch nets its payments minus the refunds it absorbs and the fees "
            "of its payments.\n"
            "- Each batch is paid out as exactly one bank credit for its net amount, dated the "
            "batch date plus the settlement lag in business days.\n\n"
            f"Settlement lag: {lag} business days\n\n"
            f"Amounts are compared exactly in {config.currency} cents: there is no tolerance. "
            "A record that one source has and another lacks, an amount that differs, or a "
            "reference that points to the wrong record is a discrepancy to investigate, not an "
            "error to correct automatically.\n"
        ),
    }


def render(dataset: Dataset, config: Config, seed: int) -> dict[str, str]:
    """Every output file as text, keyed by its relative path. Deterministic by construction."""
    files: dict[str, str] = {}
    for record_type, records in dataset.records.items():
        rows = [to_row(r) for r in records]
        files[f"{record_type}.csv"] = to_csv(record_type, rows)
        files[f"{record_type}.json"] = dumps(
            {"schema_version": RECORD_SCHEMA_VERSION, "record_type": record_type, "records": rows}
        )
    for name, text in policy_documents(config).items():
        files[f"policies/{name}"] = text
    files["ground_truth.json"] = dumps(dataset.ground_truth)
    config_json = json.dumps(config.to_dict(), sort_keys=True, separators=(",", ":"))
    files["manifest.json"] = dumps(
        {
            "simulator_version": __version__,
            "seed": seed,
            "config_sha256": hashlib.sha256(config_json.encode()).hexdigest(),
            "config": config.to_dict(),
            "affected_orders": dataset.affected_orders,
            "files": {
                path: hashlib.sha256(text.encode()).hexdigest()
                for path, text in sorted(files.items())
            },
        }
    )
    return files


def write(files: dict[str, str], out: Path) -> None:
    for path, text in files.items():
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="")
