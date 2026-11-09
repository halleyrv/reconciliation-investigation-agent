"""Source record types. Field names are the exported column names, in schema order."""

from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal

CENT = Decimal("0.01")


def money(value: Decimal) -> str:
    """Format an amount as a decimal string with exactly two places."""
    return str(value.quantize(CENT))


def timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Order:
    order_id: str
    customer_name: str
    customer_email: str
    placed_at: datetime
    total_amount: Decimal
    currency: str
    status: str


@dataclass
class Payment:
    payment_id: str
    order_ref: str
    gateway: str
    amount: Decimal
    currency: str
    captured_at: datetime
    settlement_ref: str = ""


@dataclass
class Fee:
    fee_id: str
    payment_ref: str
    gateway: str
    fee_type: str
    amount: Decimal
    currency: str
    settlement_ref: str = ""


@dataclass
class Refund:
    refund_id: str
    payment_ref: str
    gateway: str
    amount: Decimal
    currency: str
    refunded_at: datetime
    settlement_ref: str = ""


@dataclass
class Authorization:
    authorization_id: str
    subject_kind: str
    subject_ref: str
    approved_by: str
    approved_at: datetime
    max_amount: Decimal
    currency: str


@dataclass
class Settlement:
    settlement_id: str
    gateway: str
    batch_date: date
    net_amount: Decimal
    currency: str


@dataclass
class BankTransaction:
    bank_transaction_id: str
    account_ref: str
    direction: str
    value_date: date
    amount: Decimal
    currency: str
    description: str


type Record = Order | Payment | Fee | Refund | Authorization | Settlement | BankTransaction

# Record type name (also the output file stem and the ground-truth `source`) per class.
RECORD_TYPES: dict[str, type[Record]] = {
    "orders": Order,
    "payments": Payment,
    "fees": Fee,
    "refunds": Refund,
    "authorizations": Authorization,
    "settlements": Settlement,
    "bank_transactions": BankTransaction,
}


def to_row(record: Record) -> dict[str, str]:
    """Every exported field is a string, so CSV and JSON carry identical values."""
    row: dict[str, str] = {}
    for f in fields(record):
        value = getattr(record, f.name)
        if isinstance(value, Decimal):
            row[f.name] = money(value)
        elif isinstance(value, datetime):
            row[f.name] = timestamp(value)
        elif isinstance(value, date):
            row[f.name] = value.isoformat()
        else:
            row[f.name] = str(value)
    return row
