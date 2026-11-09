"""Controlled anomaly injectors. Adding an anomaly adds one function and one registry entry.

Each injector owns its target exclusively (one order, or one settlement batch), so no
record belongs to two anomalies, and declares the invariants it breaks.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from simulator.records import BankTransaction, Order, Settlement
from simulator.sim import ACCOUNT_REF, Sim, add_business_days, cents, count_for, round_cents

type RecordRef = tuple[str, str]


@dataclass(frozen=True)
class Anomaly:
    type: str
    subtype: str
    records: tuple[RecordRef, ...]
    expected_delta: Decimal
    description: str
    injector: str
    invariants: tuple[str, ...]


type Target = Order | Settlement | None
type Effect = tuple[str, tuple[RecordRef, ...], Decimal, str]


@dataclass(frozen=True)
class Injector:
    name: str
    anomaly_type: str
    subtype: str
    invariants: tuple[str, ...]
    # "records" runs before settlements exist; "bank" runs on built settlements and credits.
    phase: Literal["records", "bank"]
    target: Literal["order", "refundable_order", "settlement", "none"]
    effect: Callable[[Sim, Target], Effect]

    def apply(self, sim: Sim, target: Target) -> Anomaly:
        subtype, records, delta, description = self.effect(sim, target)
        return Anomaly(
            self.anomaly_type, subtype, records, delta, description, self.name, self.invariants
        )


def _order(target: Target) -> Order:
    assert isinstance(target, Order)
    return target


def _settlement(target: Target) -> Settlement:
    assert isinstance(target, Settlement)
    return target


def _credit_of(sim: Sim, settlement: Settlement) -> BankTransaction:
    return next(
        b for b in sim.bank_transactions if settlement.settlement_id in b.description.split()
    )


def duplicate_payment(sim: Sim, target: Target) -> Effect:
    order = _order(target)
    original = sim.payment_of(order)
    captured = original.captured_at + timedelta(seconds=sim.rng.randint(30, 600))
    duplicate = sim.add_payment(order.order_id, original.gateway, original.amount, captured)
    records = (
        ("orders", order.order_id),
        ("payments", original.payment_id),
        ("payments", duplicate.payment_id),
    )
    return "", records, original.amount, "Order captured twice by the gateway"


def unauthorized_refund(sim: Sim, target: Target) -> Effect:
    order = _order(target)
    payment = sim.payment_of(order)
    amount = round_cents(payment.amount * sim.rng.randint(20, 100) / Decimal(100))
    refund = sim.add_refund(payment, amount, sim.refund_time(payment), authorize=False)
    records = (
        ("orders", order.order_id),
        ("payments", payment.payment_id),
        ("refunds", refund.refund_id),
    )
    return "", records, -amount, "Refund issued without an internal authorization"


def incorrect_fee(sim: Sim, target: Target) -> Effect:
    payment = sim.payment_of(_order(target))
    fee = next(f for f in sim.fees if f.payment_ref == payment.payment_id)
    overcharge = cents(sim.rng.randint(5, 200))
    fee.amount += overcharge
    records = (("payments", payment.payment_id), ("fees", fee.fee_id))
    return "", records, overcharge, "Gateway fee differs from the published fee schedule"


def missing_in_orders(sim: Sim, target: Target) -> Effect:
    config = sim.config
    day = config.period_start + timedelta(
        days=sim.rng.randint(0, (config.period_end - config.period_start).days)
    )
    captured = datetime.combine(day, time(), UTC) + timedelta(seconds=sim.rng.randint(0, 86_399))
    amount = cents(sim.rng.randint(1_000, 50_000))
    gateway = sim.rng.choice(sorted(config.gateways))
    payment = sim.add_payment(sim.next_id("ORD"), gateway, amount, captured)
    fee = sim.fees[-1]
    records = (("payments", payment.payment_id), ("fees", fee.fee_id))
    return "missing_in_orders", records, amount, "Gateway payment for an order the shop never sent"


def partial_payment(sim: Sim, target: Target) -> Effect:
    order = _order(target)
    payment = sim.payment_of(order)
    payment.amount = round_cents(order.total_amount * sim.rng.randint(50, 95) / Decimal(100))
    fee = next(f for f in sim.fees if f.payment_ref == payment.payment_id)
    fee.amount = sim.fee_for(payment.gateway, payment.amount)
    records = (("orders", order.order_id), ("payments", payment.payment_id))
    delta = payment.amount - order.total_amount
    return "", records, delta, "Customer paid less than the order total"


def inconsistent_reference(sim: Sim, target: Target) -> Effect:
    order = _order(target)
    payment = sim.payment_of(order)
    variants = (
        order.order_id.replace("-", ""),
        order.order_id.lower(),
        order.order_id.replace("-", "_"),
    )
    payment.order_ref = sim.rng.choice(variants)
    records = (("orders", order.order_id), ("payments", payment.payment_id))
    description = f"Gateway reports order reference {payment.order_ref!r} for {order.order_id}"
    return "", records, Decimal("0.00"), description


def out_of_order_event(sim: Sim, target: Target) -> Effect:
    order = _order(target)
    payment = sim.payment_of(order)
    order.placed_at = payment.captured_at + timedelta(seconds=sim.rng.randint(60, 3_600))
    records = (("orders", order.order_id), ("payments", payment.payment_id))
    return "payment_before_order", records, Decimal("0.00"), "Payment captured before the order"


def duplicate_refund(sim: Sim, target: Target) -> Effect:
    order = _order(target)
    payment = sim.payment_of(order)
    amount = round_cents(payment.amount * sim.rng.randint(60, 100) / Decimal(100))
    first = sim.add_refund(payment, amount, sim.refund_time(payment), authorize=True)
    authorization = sim.authorizations[-1]
    later = first.refunded_at + timedelta(minutes=sim.rng.randint(1, 120))
    second = sim.add_refund(payment, amount, later, authorize=False)
    records = (
        ("orders", order.order_id),
        ("payments", payment.payment_id),
        ("refunds", first.refund_id),
        ("refunds", second.refund_id),
        ("authorizations", authorization.authorization_id),
    )
    return "", records, -amount, "One authorized refund was issued twice"


def conflicting_resent_record(sim: Sim, target: Target) -> Effect:
    order = _order(target)
    email = sim.fake.email()
    while email == order.customer_email:
        email = sim.fake.email()
    sim.orders.append(replace(order, customer_email=email))
    description = "Shop re-sent the order with the same ID and a different customer email"
    return "orders", (("orders", order.order_id),), Decimal("0.00"), description


def delayed_settlement(sim: Sim, target: Target) -> Effect:
    settlement = _settlement(target)
    credit = _credit_of(sim, settlement)
    credit.value_date = add_business_days(credit.value_date, sim.rng.randint(1, 3))
    records = (
        ("settlements", settlement.settlement_id),
        ("bank_transactions", credit.bank_transaction_id),
    )
    return "", records, Decimal("0.00"), "Payout reached the bank later than the settlement lag"


def incorrect_amount(sim: Sim, target: Target) -> Effect:
    settlement = _settlement(target)
    credit = _credit_of(sim, settlement)
    delta = cents(sim.rng.randint(100, 5_000))
    if sim.rng.random() < 0.5 and credit.amount - delta > 0:
        delta = -delta
    credit.amount += delta
    records = (
        ("settlements", settlement.settlement_id),
        ("bank_transactions", credit.bank_transaction_id),
    )
    return "", records, delta, "Bank credit amount differs from the settlement net"


def missing_in_bank(sim: Sim, target: Target) -> Effect:
    settlement = _settlement(target)
    sim.bank_transactions.remove(_credit_of(sim, settlement))
    records = (("settlements", settlement.settlement_id),)
    return "missing_in_bank", records, -settlement.net_amount, "Settlement never paid out"


def missing_in_gateway(sim: Sim, target: Target) -> Effect:
    config = sim.config
    gateway = sim.rng.choice(sorted(config.gateways))
    day = config.period_start + timedelta(
        days=sim.rng.randint(0, (config.period_end - config.period_start).days)
    )
    amount = cents(sim.rng.randint(5_000, 100_000))
    credit = BankTransaction(
        sim.bank_id(),
        ACCOUNT_REF,
        "credit",
        add_business_days(day, config.settlement_lag_business_days),
        amount,
        config.currency,
        sim.payout_description(gateway, sim.next_id("STL")),
    )
    sim.bank_transactions.append(credit)
    sim.bank_transactions.sort(key=lambda b: (b.value_date, b.description))
    records = (("bank_transactions", credit.bank_transaction_id),)
    return "missing_in_gateway", records, amount, "Bank credit with no settlement or payment"


INJECTORS: tuple[Injector, ...] = (
    Injector("duplicate_payment", "duplicate_payment", "", ("I1",), "records", "order",
             duplicate_payment),
    Injector("unauthorized_refund", "unauthorized_refund", "", ("I3",), "records",
             "refundable_order", unauthorized_refund),
    Injector("incorrect_fee", "incorrect_fee", "", ("I4",), "records", "order", incorrect_fee),
    Injector("missing_in_orders", "missing_transaction", "missing_in_orders", ("I1",),
             "records", "none", missing_in_orders),
    Injector("missing_in_bank", "missing_transaction", "missing_in_bank", ("I5",), "bank",
             "settlement", missing_in_bank),
    Injector("missing_in_gateway", "missing_transaction", "missing_in_gateway", ("I5",),
             "bank", "none", missing_in_gateway),
    Injector("partial_payment", "partial_payment", "", ("I1",), "records", "order",
             partial_payment),
    Injector("delayed_settlement", "delayed_settlement", "", ("I5",), "bank", "settlement",
             delayed_settlement),
    Injector("incorrect_amount", "incorrect_amount", "", ("I5",), "bank", "settlement",
             incorrect_amount),
    Injector("inconsistent_reference", "inconsistent_reference", "", ("I1",), "records", "order",
             inconsistent_reference),
    Injector("out_of_order_event", "out_of_order_event", "", ("I6",), "records", "order",
             out_of_order_event),
    Injector("duplicate_refund", "duplicate_refund", "", ("I2", "I3"), "records",
             "refundable_order", duplicate_refund),
    Injector("conflicting_resent_record", "conflicting_resent_record", "", ("I7",), "records",
             "order", conflicting_resent_record),
)  # fmt: skip


def planned_counts(rates: dict[str, Decimal], orders: int) -> dict[str, int]:
    """Instances per injector. A type with several injectors splits its count round-robin."""
    counts: dict[str, int] = {}
    for anomaly_type, rate in rates.items():
        injectors = [i for i in INJECTORS if i.anomaly_type == anomaly_type]
        total = count_for(rate, orders)
        for index, injector in enumerate(injectors):
            counts[injector.name] = total // len(injectors) + (index < total % len(injectors))
    return counts
