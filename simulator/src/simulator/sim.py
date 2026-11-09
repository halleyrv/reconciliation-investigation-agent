"""Simulation state and the building blocks of a clean (anomaly-free) dataset."""

import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from faker import Faker

from simulator.config import Config
from simulator.records import (
    CENT,
    Authorization,
    BankTransaction,
    Fee,
    Order,
    Payment,
    Refund,
    Settlement,
)

ACCOUNT_REF = "ACC-0001"
# A refund is dated up to 5 days after its payment; 6 days keeps it inside the period.
REFUND_WINDOW_DAYS = 5


type BatchKey = tuple[date, str]


class GenerationError(RuntimeError):
    pass


def cents(value: int) -> Decimal:
    return Decimal(value).scaleb(-2)


def round_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


def add_business_days(day: date, days: int) -> date:
    """Monday-Friday business days, no holidays (assumption A4)."""
    current = day
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def count_for(rate: Decimal, population: int) -> int:
    return int((rate * population).to_integral_value(rounding=ROUND_HALF_EVEN))


class Sim:
    def __init__(self, config: Config, seed: int) -> None:
        self.config = config
        self.rng = random.Random(seed)
        self.fake = Faker("en_US")
        self.fake.seed_instance(seed)
        self.orders: list[Order] = []
        self.payments: list[Payment] = []
        self.fees: list[Fee] = []
        self.refunds: list[Refund] = []
        self.authorizations: list[Authorization] = []
        self.settlements: list[Settlement] = []
        self.bank_transactions: list[BankTransaction] = []
        self.claimed_orders: set[str] = set()
        self.claimed_settlements: set[str] = set()
        # Batches picked for settlement-level anomalies before any other anomaly is
        # injected, so no anomalous payment or refund ends up inside one (no overlap).
        self.reserved_batches: dict[str, list[BatchKey]] = {}
        self.anomalous_refunds: set[str] = set()
        self._sequences: dict[str, int] = {}
        self._bank_ids: set[str] = set()

    # --- identifiers -----------------------------------------------------

    def next_id(self, prefix: str) -> str:
        self._sequences[prefix] = self._sequences.get(prefix, 0) + 1
        return f"{prefix}-{self._sequences[prefix]:06d}"

    def bank_id(self) -> str:
        # Banks use opaque references; random IDs also avoid gaps that would leak anomalies.
        while True:
            candidate = f"BNK-{self.rng.getrandbits(40):010X}"
            if candidate not in self._bank_ids:
                self._bank_ids.add(candidate)
                return candidate

    # --- money -----------------------------------------------------------

    def fee_for(self, gateway: str, amount: Decimal) -> Decimal:
        schedule = self.config.gateways[gateway]
        return round_cents(amount * schedule.percentage_bps / Decimal(10_000) + schedule.fixed_fee)

    # --- record factories --------------------------------------------------

    def add_payment(
        self, order_ref: str, gateway: str, amount: Decimal, captured_at: datetime
    ) -> Payment:
        currency = self.config.currency
        payment = Payment(self.next_id("PAY"), order_ref, gateway, amount, currency, captured_at)
        self.payments.append(payment)
        fee_amount = self.fee_for(gateway, amount)
        fee = Fee(
            self.next_id("FEE"), payment.payment_id, gateway, "processing", fee_amount, currency
        )
        self.fees.append(fee)
        return payment

    def add_refund(
        self,
        payment: Payment,
        amount: Decimal,
        refunded_at: datetime,
        *,
        authorize: bool,
        anomalous: bool = False,
    ) -> Refund:
        currency = self.config.currency
        refund = Refund(
            self.next_id("RFD"), payment.payment_id, payment.gateway, amount, currency, refunded_at
        )
        self.refunds.append(refund)
        if anomalous:
            self.anomalous_refunds.add(refund.refund_id)
        if authorize:
            approved_at = refunded_at - timedelta(minutes=self.rng.randint(5, 240))
            self.authorizations.append(
                Authorization(
                    self.next_id("AUT"),
                    "refund",
                    refund.refund_id,
                    self.fake.name(),
                    approved_at,
                    amount,
                    currency,
                )
            )
        return refund

    def refund_time(self, payment: Payment) -> datetime:
        delay = self.rng.randint(86_400, REFUND_WINDOW_DAYS * 86_400)
        return payment.captured_at + timedelta(seconds=delay)

    def payment_of(self, order: Order) -> Payment:
        return next(p for p in self.payments if p.order_ref == order.order_id)

    # --- target selection --------------------------------------------------

    def refundable(self, order: Order) -> bool:
        last_day = self.config.period_end - timedelta(days=REFUND_WINDOW_DAYS + 1)
        return self.payment_of(order).captured_at.date() <= last_day

    def batch_keys(self) -> list[BatchKey]:
        return sorted({(p.captured_at.date(), p.gateway) for p in self.payments})

    def is_reserved(self, key: BatchKey) -> bool:
        return any(key in keys for keys in self.reserved_batches.values())

    def unreserved_batch_keys(self) -> list[BatchKey]:
        return [k for k in self.batch_keys() if not self.is_reserved(k)]

    def reserve_batches(self, owner: str, count: int) -> None:
        pool = self.unreserved_batch_keys()
        if count > len(pool):
            raise GenerationError(f"not enough settlement batches: need {count}, have {len(pool)}")
        self.reserved_batches[owner] = self.rng.sample(pool, count)

    def claim_orders(
        self, count: int, *, refundable: bool = False, anomalous: bool = True
    ) -> list[Order]:
        def eligible(order: Order) -> bool:
            # Claimed orders first: an anomaly may have rewritten their payment's order_ref.
            if order.order_id in self.claimed_orders:
                return False
            payment = self.payment_of(order)
            key = (payment.captured_at.date(), payment.gateway)
            return (not refundable or self.refundable(order)) and not (
                anomalous and self.is_reserved(key)
            )

        pool = [o for o in self.orders if eligible(o)]
        if count > len(pool):
            raise GenerationError(f"not enough eligible orders: need {count}, have {len(pool)}")
        chosen = self.rng.sample(pool, count)
        self.claimed_orders.update(o.order_id for o in chosen)
        return chosen

    def claim_settlements(self, owner: str) -> list[Settlement]:
        by_key = {(s.batch_date, s.gateway): s for s in self.settlements}
        chosen = [by_key[key] for key in self.reserved_batches.get(owner, [])]
        self.claimed_settlements.update(s.settlement_id for s in chosen)
        return chosen

    # --- clean dataset steps -------------------------------------------------

    def generate_orders_and_payments(self) -> None:
        config = self.config
        start = datetime.combine(config.period_start, time(), UTC)
        span = int((config.period_end - config.period_start).total_seconds()) + 86_399
        gateways = sorted(config.gateways)
        drafts = [
            (
                start + timedelta(seconds=self.rng.randint(0, span)),
                cents(self.rng.randint(1_000, 50_000)),
                self.fake.name(),
                self.fake.email(),
                self.rng.choice(gateways),
                self.rng.randint(30, 3_600),
            )
            for _ in range(config.orders)
        ]
        drafts.sort(key=lambda d: d[0])
        for placed_at, total, name, email, gateway, capture_delay in drafts:
            order = Order(
                self.next_id("ORD"), name, email, placed_at, total, config.currency, "completed"
            )
            self.orders.append(order)
            self.add_payment(
                order.order_id, gateway, total, placed_at + timedelta(seconds=capture_delay)
            )

    def generate_refunds(self) -> None:
        chosen = self.claim_orders(
            count_for(self.config.refund_rate, self.config.orders),
            refundable=True,
            anomalous=False,
        )
        # A normal refund is not an anomaly: its order keeps its expected link.
        self.claimed_orders.difference_update(o.order_id for o in chosen)
        for order in chosen:
            payment = self.payment_of(order)
            if self.rng.random() < 0.5:
                amount = payment.amount
            else:
                amount = round_cents(payment.amount * self.rng.randint(10, 90) / Decimal(100))
            self.add_refund(payment, amount, self.refund_time(payment), authorize=True)

    def build_settlements(self) -> None:
        """One batch per gateway and capture day; refunds are netted in a later batch."""
        keys = sorted({(p.captured_at.date(), p.gateway) for p in self.payments})
        batches: dict[tuple[date, str], Settlement] = {}
        for day, gateway in keys:
            settlement = Settlement(
                self.next_id("STL"), gateway, day, Decimal("0.00"), self.config.currency
            )
            batches[(day, gateway)] = settlement
            self.settlements.append(settlement)
        fee_by_payment = {f.payment_ref: f for f in self.fees}
        for payment in self.payments:
            settlement = batches[(payment.captured_at.date(), payment.gateway)]
            payment.settlement_ref = settlement.settlement_id
            settlement.net_amount += payment.amount
            fee = fee_by_payment[payment.payment_id]
            fee.settlement_ref = settlement.settlement_id
            settlement.net_amount -= fee.amount
        payments = {p.payment_id: p for p in self.payments}
        for refund in sorted(self.refunds, key=lambda r: (r.refunded_at, r.refund_id)):
            payment = payments[refund.payment_ref]

            def fits(s: Settlement, earliest: date, refund: Refund = refund) -> bool:
                return (
                    s.gateway == refund.gateway
                    and s.batch_date >= earliest
                    and s.net_amount - refund.amount > 0
                    and not (
                        refund.refund_id in self.anomalous_refunds
                        and self.is_reserved((s.batch_date, s.gateway))
                    )
                )

            candidates = [s for s in self.settlements if fits(s, refund.refunded_at.date())]
            if not candidates:
                # Late in the period no later batch may be large enough: issue the refund
                # earlier instead, in the first batch since its payment that can absorb it.
                candidates = [s for s in self.settlements if fits(s, payment.captured_at.date())]
                if not candidates:
                    raise GenerationError(f"no settlement batch can absorb {refund.refund_id}")
                self._redate_refund(refund, payment, candidates[0].batch_date)
            settlement = candidates[0]
            refund.settlement_ref = settlement.settlement_id
            settlement.net_amount -= refund.amount

    def _redate_refund(self, refund: Refund, payment: Payment, batch_date: date) -> None:
        """Move a refund (and its authorizations, keeping their lead time) to an earlier day."""
        start_of_day = datetime.combine(batch_date, time(), UTC)
        new_time = max(payment.captured_at + timedelta(minutes=1), start_of_day)
        shift = refund.refunded_at - new_time
        refund.refunded_at = new_time
        for authorization in self.authorizations:
            if authorization.subject_ref == refund.refund_id:
                authorization.approved_at -= shift

    def build_bank_credits(self) -> None:
        lag = self.config.settlement_lag_business_days
        for settlement in self.settlements:
            self.bank_transactions.append(
                BankTransaction(
                    self.bank_id(),
                    ACCOUNT_REF,
                    "credit",
                    add_business_days(settlement.batch_date, lag),
                    settlement.net_amount,
                    settlement.currency,
                    self.payout_description(settlement.gateway, settlement.settlement_id),
                )
            )
        self.bank_transactions.sort(key=lambda b: (b.value_date, b.description))

    def payout_description(self, gateway: str, settlement_ref: str) -> str:
        trace = self.rng.randint(10_000_000, 99_999_999)
        return f"{gateway.upper()} PAYOUT {settlement_ref} TRACE {trace}"
