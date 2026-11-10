"""Reconciliation's read-only view of the canonical source records (owned by Ingestion)."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from recon.shared_kernel.money import Money


class Source(StrEnum):
    """A record type, named like the simulator file it comes from."""

    ORDERS = "orders"
    PAYMENTS = "payments"
    REFUNDS = "refunds"
    FEES = "fees"
    SETTLEMENTS = "settlements"
    BANK_TRANSACTIONS = "bank_transactions"
    AUTHORIZATIONS = "authorizations"


@dataclass(frozen=True, slots=True, order=True)
class RecordRef:
    source: Source
    external_id: str


@dataclass(frozen=True, slots=True)
class Order:
    external_id: str
    placed_at: datetime
    total: Money

    @property
    def ref(self) -> RecordRef:
        return RecordRef(Source.ORDERS, self.external_id)


@dataclass(frozen=True, slots=True)
class Payment:
    external_id: str
    order_ref: str  # a claim, not a foreign key: it may resolve to nothing
    gateway: str
    amount: Money
    captured_at: datetime
    settlement_ref: str

    @property
    def ref(self) -> RecordRef:
        return RecordRef(Source.PAYMENTS, self.external_id)


@dataclass(frozen=True, slots=True)
class Refund:
    external_id: str
    payment_ref: str
    gateway: str
    amount: Money
    refunded_at: datetime
    settlement_ref: str

    @property
    def ref(self) -> RecordRef:
        return RecordRef(Source.REFUNDS, self.external_id)


@dataclass(frozen=True, slots=True)
class Fee:
    external_id: str
    payment_ref: str
    gateway: str
    fee_type: str
    amount: Money
    settlement_ref: str

    @property
    def ref(self) -> RecordRef:
        return RecordRef(Source.FEES, self.external_id)


@dataclass(frozen=True, slots=True)
class Settlement:
    external_id: str
    gateway: str
    batch_date: date
    net_amount: Money

    @property
    def ref(self) -> RecordRef:
        return RecordRef(Source.SETTLEMENTS, self.external_id)


@dataclass(frozen=True, slots=True)
class BankTransaction:
    external_id: str
    direction: str
    value_date: date
    amount: Money
    description: str  # names the settlement batch it pays out, as the gateway writes it

    @property
    def ref(self) -> RecordRef:
        return RecordRef(Source.BANK_TRANSACTIONS, self.external_id)


@dataclass(frozen=True, slots=True)
class Authorization:
    external_id: str
    subject_kind: str
    subject_ref: str
    approved_at: datetime
    max_amount: Money

    @property
    def ref(self) -> RecordRef:
        return RecordRef(Source.AUTHORIZATIONS, self.external_id)


@dataclass(frozen=True, slots=True)
class SourceConflict:
    """A re-send of a known external ID with a different payload, as Ingestion recorded it."""

    source: Source
    external_id: str

    @property
    def ref(self) -> RecordRef:
        return RecordRef(self.source, self.external_id)
