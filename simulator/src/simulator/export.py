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

RECORD_SCHEMA_VERSION = "1.0.0"


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
