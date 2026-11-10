"""An in-memory book of source records for engine tests: clean by default, tampered per test."""

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta

from recon.reconciliation.domain.calendar import BusinessCalendar
from recon.reconciliation.domain.engine import default_engine
from recon.reconciliation.domain.fees import FeeSchedule
from recon.reconciliation.domain.records import (
    Authorization,
    BankTransaction,
    Fee,
    Order,
    Payment,
    RecordRef,
    Refund,
    Settlement,
    Source,
    SourceConflict,
)
from recon.reconciliation.domain.results import ReconciliationResult
from recon.reconciliation.domain.rules import Ruleset
from recon.reconciliation.domain.snapshot import Snapshot
from recon.shared_kernel.money import Money

GATEWAY = "gateway_a"
MONDAY = date(2026, 10, 5)
SCHEDULE = FeeSchedule(GATEWAY, "processing", 290, Money(30, "USD"), date(2026, 1, 1), None)
CALENDAR = BusinessCalendar(frozenset({date(2026, 10, 9)}))
RULESET = Ruleset(fee_schedules=(SCHEDULE,), calendar=CALENDAR, settlement_lag_business_days=2)


def usd(minor: int) -> Money:
    return Money(minor, "USD")


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), UTC)


def ref(source: Source, external_id: str) -> RecordRef:
    return RecordRef(source, external_id)


@dataclass
class Book:
    orders: list[Order] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    refunds: list[Refund] = field(default_factory=list)
    fees: list[Fee] = field(default_factory=list)
    settlements: list[Settlement] = field(default_factory=list)
    bank: list[BankTransaction] = field(default_factory=list)
    authorizations: list[Authorization] = field(default_factory=list)
    conflicts: list[SourceConflict] = field(default_factory=list)

    def sale(self, n: int, total: int, *, day: date = MONDAY, batch: str = "STL-000001") -> Payment:
        order = Order(f"ORD-{n:06}", at(day, 9), usd(total))
        self.orders.append(order)
        return self.pay(f"PAY-{n:06}", order.external_id, total, at(day, 10), batch=batch)

    def pay(
        self, payment_id: str, order_ref: str, amount: int, captured: datetime, *, batch: str
    ) -> Payment:
        payment = Payment(payment_id, order_ref, GATEWAY, usd(amount), captured, batch)
        self.payments.append(payment)
        fee_id = payment_id.replace("PAY", "FEE")
        self.fees.append(
            Fee(fee_id, payment_id, GATEWAY, "processing", SCHEDULE.fee_for(payment.amount), batch)
        )
        return payment

    def refund(
        self, refund_id: str, payment: Payment, amount: int, *, authorized: bool, minutes: int = 60
    ) -> Refund:
        refunded_at = payment.captured_at + timedelta(minutes=minutes)
        refund = Refund(
            refund_id,
            payment.external_id,
            GATEWAY,
            usd(amount),
            refunded_at,
            payment.settlement_ref,
        )
        self.refunds.append(refund)
        if authorized:
            self.authorizations.append(
                Authorization(
                    refund_id.replace("RFD", "AUT"),
                    "refund",
                    refund_id,
                    refunded_at - timedelta(minutes=5),
                    usd(amount),
                )
            )
        return refund

    def close(self, batch: str = "STL-000001", day: date = MONDAY) -> None:
        """Settle a batch from its members and pay it out on time, as the gateway would."""
        net = (
            sum(p.amount.amount_minor for p in self.payments if p.settlement_ref == batch)
            - sum(r.amount.amount_minor for r in self.refunds if r.settlement_ref == batch)
            - sum(f.amount.amount_minor for f in self.fees if f.settlement_ref == batch)
        )
        self.settlements.append(Settlement(batch, GATEWAY, day, usd(net)))
        self.bank.append(
            BankTransaction(
                f"BNK-{batch[-6:]}",
                "credit",
                CALENDAR.add_business_days(day, 2),
                usd(net),
                f"GATEWAY_A PAYOUT {batch} TRACE T{batch[-6:]}",
            )
        )

    def replace_fee(self, fee_id: str, amount: int) -> None:
        self.fees = [
            replace(f, amount=usd(amount)) if f.external_id == fee_id else f for f in self.fees
        ]

    def snapshot(self) -> Snapshot:
        return Snapshot(
            currency="USD",
            orders=tuple(self.orders),
            payments=tuple(self.payments),
            refunds=tuple(self.refunds),
            fees=tuple(self.fees),
            settlements=tuple(self.settlements),
            bank_transactions=tuple(self.bank),
            authorizations=tuple(self.authorizations),
            conflicts=tuple(self.conflicts),
        )

    def run(self) -> ReconciliationResult:
        return default_engine().run(self.snapshot(), RULESET)


def clean_book() -> Book:
    """Three paid orders settled in one batch and paid out on time."""
    book = Book()
    for n, total in ((1, 10_000), (2, 12_345), (3, 5_050)):
        book.sale(n, total)
    return book


type Found = tuple[str, frozenset[RecordRef], int]


def found(result: ReconciliationResult) -> list[Found]:
    return [(d.type.value, d.records, d.delta_minor) for d in result.discrepancies]


def linked_orders(result: ReconciliationResult) -> set[str]:
    return {
        m.ref.external_id for g in result.groups for m in g.members if m.ref.source is Source.ORDERS
    }
