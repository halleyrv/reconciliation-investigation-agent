"""Reads a simulator export directory (the Published Language, AS1): ``<type>.json`` files plus
``manifest.json``. The CSV twins carry the same records and are not read (assumption A2)."""

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints, ValidationError

from recon.ingestion.application.import_export import ParsedRow, SimulatorExport, SourceFile
from recon.ingestion.domain.batch import RowError
from recon.ingestion.domain.records import (
    Authorization,
    BankTransaction,
    Fee,
    Order,
    Payment,
    RecordType,
    Refund,
    Settlement,
    SourceRecord,
    payload_digest,
)
from recon.shared_kernel.money import Money, parse_minor_units

_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or not _INSTANT.fullmatch(value):
        raise ValueError("must be a UTC instant such as 2026-10-01T03:46:51Z")
    return datetime.fromisoformat(value)  # raises ValueError on an impossible date or time


def _date(value: object) -> date:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ValueError("must be a date such as 2026-10-01")
    return date.fromisoformat(value)


def _minor_units(value: object) -> int:
    if not isinstance(value, str):
        raise ValueError(f"must be a decimal string, not a JSON {type(value).__name__}")
    minor = parse_minor_units(value)
    if minor <= 0:
        raise ValueError("must be positive")
    return minor


Instant = Annotated[datetime, BeforeValidator(_instant)]
Day = Annotated[date, BeforeValidator(_date)]
MinorUnits = Annotated[int, BeforeValidator(_minor_units)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Text = Annotated[str, StringConstraints(min_length=1)]
OrderId = Annotated[str, StringConstraints(pattern=r"^ORD-[0-9]{6}$")]
PaymentId = Annotated[str, StringConstraints(pattern=r"^PAY-[0-9]{6}$")]
RefundId = Annotated[str, StringConstraints(pattern=r"^RFD-[0-9]{6}$")]
FeeId = Annotated[str, StringConstraints(pattern=r"^FEE-[0-9]{6}$")]
SettlementId = Annotated[str, StringConstraints(pattern=r"^STL-[0-9]{6}$")]
BankTransactionId = Annotated[str, StringConstraints(pattern=r"^BNK-[0-9A-F]{10}$")]
AuthorizationId = Annotated[str, StringConstraints(pattern=r"^AUT-[0-9]{6}$")]


class _Row(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    def to_record(self) -> SourceRecord:
        raise NotImplementedError


class _OrderRow(_Row):
    order_id: OrderId
    customer_name: Text
    customer_email: Text
    placed_at: Instant
    total_amount: MinorUnits
    currency: Currency
    status: Text

    def to_record(self) -> Order:
        total = Money(self.total_amount, self.currency)
        return Order(
            self.order_id,
            self.customer_name,
            self.customer_email,
            self.placed_at,
            total,
            self.status,
        )


class _PaymentRow(_Row):
    payment_id: PaymentId
    order_ref: Text
    gateway: Text
    amount: MinorUnits
    currency: Currency
    captured_at: Instant
    settlement_ref: Text

    def to_record(self) -> Payment:
        amount = Money(self.amount, self.currency)
        return Payment(
            self.payment_id,
            self.order_ref,
            self.gateway,
            amount,
            self.captured_at,
            self.settlement_ref,
        )


class _RefundRow(_Row):
    refund_id: RefundId
    payment_ref: Text
    gateway: Text
    amount: MinorUnits
    currency: Currency
    refunded_at: Instant
    settlement_ref: Text

    def to_record(self) -> Refund:
        amount = Money(self.amount, self.currency)
        return Refund(
            self.refund_id,
            self.payment_ref,
            self.gateway,
            amount,
            self.refunded_at,
            self.settlement_ref,
        )


class _FeeRow(_Row):
    fee_id: FeeId
    payment_ref: Text
    gateway: Text
    fee_type: Text
    amount: MinorUnits
    currency: Currency
    settlement_ref: Text

    def to_record(self) -> Fee:
        amount = Money(self.amount, self.currency)
        return Fee(
            self.fee_id, self.payment_ref, self.gateway, self.fee_type, amount, self.settlement_ref
        )


class _SettlementRow(_Row):
    settlement_id: SettlementId
    gateway: Text
    batch_date: Day
    net_amount: MinorUnits
    currency: Currency

    def to_record(self) -> Settlement:
        net = Money(self.net_amount, self.currency)
        return Settlement(self.settlement_id, self.gateway, self.batch_date, net)


class _BankTransactionRow(_Row):
    bank_transaction_id: BankTransactionId
    account_ref: Text
    direction: Literal["credit", "debit"]
    value_date: Day
    amount: MinorUnits
    currency: Currency
    description: Text

    def to_record(self) -> BankTransaction:
        amount = Money(self.amount, self.currency)
        return BankTransaction(
            self.bank_transaction_id,
            self.account_ref,
            self.direction,
            self.value_date,
            amount,
            self.description,
        )


class _AuthorizationRow(_Row):
    authorization_id: AuthorizationId
    subject_kind: Literal["refund", "write_off"]
    subject_ref: Text
    approved_by: Text
    approved_at: Instant
    max_amount: MinorUnits
    currency: Currency

    def to_record(self) -> Authorization:
        max_amount = Money(self.max_amount, self.currency)
        return Authorization(
            self.authorization_id,
            self.subject_kind,
            self.subject_ref,
            self.approved_by,
            self.approved_at,
            max_amount,
        )


_ROWS: dict[RecordType, type[_Row]] = {
    RecordType.ORDERS: _OrderRow,
    RecordType.PAYMENTS: _PaymentRow,
    RecordType.REFUNDS: _RefundRow,
    RecordType.FEES: _FeeRow,
    RecordType.SETTLEMENTS: _SettlementRow,
    RecordType.BANK_TRANSACTIONS: _BankTransactionRow,
    RecordType.AUTHORIZATIONS: _AuthorizationRow,
}


class _Envelope(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal["1.0.0"]
    record_type: str
    records: list[dict[str, object]]


def read_export(directory: Path) -> SimulatorExport:
    manifest = json.loads((directory / "manifest.json").read_bytes())["files"]
    files = tuple(_read_file(directory, record_type) for record_type in RecordType)
    return SimulatorExport(manifest, files)


def _read_file(directory: Path, record_type: RecordType) -> SourceFile:
    name = f"{record_type.value}.json"
    content = (directory / name).read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    try:
        envelope = _Envelope.model_validate_json(content)
    except ValidationError as exc:
        return SourceFile(name, sha256, record_type, (), tuple(_errors(name, 0, exc)))
    if envelope.record_type != record_type.value:
        message = f"expected {record_type.value!r}, got {envelope.record_type!r}"
        return SourceFile(
            name, sha256, record_type, (), (RowError(name, 0, "record_type", message),)
        )
    row_model = _ROWS[record_type]
    rows: list[ParsedRow] = []
    errors: list[RowError] = []
    for line_no, payload in enumerate(envelope.records, 1):
        try:
            record = row_model.model_validate(payload).to_record()
        except ValidationError as exc:
            errors.extend(_errors(name, line_no, exc))
            continue
        rows.append(ParsedRow(line_no, payload, payload_digest(payload), record))
    if errors:
        return SourceFile(name, sha256, record_type, (), tuple(errors))
    return SourceFile(name, sha256, record_type, tuple(rows), ())


def _errors(name: str, line_no: int, exc: ValidationError) -> list[RowError]:
    """``line_no`` 0 means the error is about the file envelope, not one record."""
    return [
        RowError(name, line_no, ".".join(str(part) for part in e["loc"]) or "(file)", e["msg"])
        for e in exc.errors()
    ]
