"""Canonical source records: what each source said, normalized. Immutable once created."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from recon.shared_kernel.money import Money


class RecordType(StrEnum):
    """One value per simulator file, in import order."""

    ORDERS = "orders"
    PAYMENTS = "payments"
    REFUNDS = "refunds"
    FEES = "fees"
    SETTLEMENTS = "settlements"
    BANK_TRANSACTIONS = "bank_transactions"
    AUTHORIZATIONS = "authorizations"


# The system that produces each record type (one data source per producing system).
SOURCE_OF: dict[RecordType, str] = {
    RecordType.ORDERS: "shop",
    RecordType.PAYMENTS: "gateway",
    RecordType.REFUNDS: "gateway",
    RecordType.FEES: "gateway",
    RecordType.SETTLEMENTS: "gateway",
    RecordType.BANK_TRANSACTIONS: "bank",
    RecordType.AUTHORIZATIONS: "back_office",
}


def _require_positive(name: str, money: Money) -> None:
    if money.amount_minor <= 0:
        raise ValueError(f"{name} must be positive, got {money.amount_minor} minor units")


@dataclass(frozen=True, slots=True)
class Order:
    external_id: str
    customer_name: str
    customer_email: str
    placed_at: datetime
    total: Money
    status: str

    def __post_init__(self) -> None:
        _require_positive("total", self.total)


@dataclass(frozen=True, slots=True)
class Payment:
    external_id: str
    order_external_ref: str
    gateway: str
    amount: Money
    captured_at: datetime
    settlement_batch_ref: str

    def __post_init__(self) -> None:
        _require_positive("amount", self.amount)


@dataclass(frozen=True, slots=True)
class Refund:
    external_id: str
    payment_external_ref: str
    gateway: str
    amount: Money
    refunded_at: datetime
    settlement_batch_ref: str

    def __post_init__(self) -> None:
        _require_positive("amount", self.amount)


@dataclass(frozen=True, slots=True)
class Fee:
    external_id: str
    payment_external_ref: str
    gateway: str
    fee_type: str
    amount: Money
    settlement_batch_ref: str

    def __post_init__(self) -> None:
        _require_positive("amount", self.amount)


@dataclass(frozen=True, slots=True)
class Settlement:
    """The gateway's settlement report: the net it declares for one batch (ADR-0011)."""

    external_id: str
    gateway: str
    batch_date: date
    net_amount: Money

    def __post_init__(self) -> None:
        _require_positive("net_amount", self.net_amount)


@dataclass(frozen=True, slots=True)
class BankTransaction:
    external_id: str
    account_ref: str
    direction: Literal["credit", "debit"]
    value_date: date
    amount: Money
    description: str

    def __post_init__(self) -> None:
        _require_positive("amount", self.amount)


@dataclass(frozen=True, slots=True)
class Authorization:
    external_id: str
    subject_kind: Literal["refund", "write_off"]
    subject_external_ref: str
    approved_by: str
    approved_at: datetime
    max_amount: Money

    def __post_init__(self) -> None:
        _require_positive("max_amount", self.max_amount)


type SourceRecord = Order | Payment | Refund | Fee | Settlement | BankTransaction | Authorization


@dataclass(frozen=True, slots=True)
class RawRecord:
    """What arrived, byte for byte in meaning: one record object of a file (register R6)."""

    id: uuid.UUID
    batch_id: uuid.UUID
    source: str
    line_no: int
    payload: dict[str, object]
    payload_sha256: str


def payload_digest(payload: dict[str, object]) -> str:
    """SHA-256 of the payload in canonical JSON, so key order and spacing never matter."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceConflict:
    """A re-send of an existing external ID with a different payload. Never an update."""

    id: uuid.UUID
    source: str
    record_type: RecordType
    external_id: str
    existing_raw_record_id: uuid.UUID
    incoming_raw_record_id: uuid.UUID
    detected_at: datetime
