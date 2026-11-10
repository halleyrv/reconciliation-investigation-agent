"""The records a run reconciles, with the lookups every rule shares. Read-only."""

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cached_property

from recon.reconciliation.domain.records import (
    Authorization,
    BankTransaction,
    Fee,
    Order,
    Payment,
    Refund,
    Settlement,
    SourceConflict,
)

# The gateway names the batch in the payout description: "GATEWAY_A PAYOUT STL-000123 TRACE ..."
_SETTLEMENT_REF = re.compile(r"\bSTL-[0-9]+\b")


def normalize_reference(reference: str) -> str:
    """Case and separators removed: ``ord_000006`` and ``ORD-000006`` normalize alike."""
    return re.sub(r"[^0-9A-Z]", "", reference.upper())


def _group[K, V](items: Iterable[V], key: Callable[[V], K]) -> dict[K, list[V]]:
    groups: dict[K, list[V]] = defaultdict(list)
    for item in items:
        groups[key(item)].append(item)
    return dict(groups)


@dataclass(frozen=True)
class Snapshot:
    currency: str
    orders: tuple[Order, ...]
    payments: tuple[Payment, ...]
    refunds: tuple[Refund, ...]
    fees: tuple[Fee, ...]
    settlements: tuple[Settlement, ...]
    bank_transactions: tuple[BankTransaction, ...]
    authorizations: tuple[Authorization, ...]
    conflicts: tuple[SourceConflict, ...]

    @cached_property
    def orders_by_id(self) -> dict[str, Order]:
        return {o.external_id: o for o in self.orders}

    @cached_property
    def payments_by_id(self) -> dict[str, Payment]:
        return {p.external_id: p for p in self.payments}

    @cached_property
    def settlements_by_id(self) -> dict[str, Settlement]:
        return {s.external_id: s for s in self.settlements}

    @cached_property
    def payments_by_order(self) -> dict[str, list[Payment]]:
        """Payments whose order reference names an existing order exactly."""
        return _group(
            (p for p in self.payments if p.order_ref in self.orders_by_id), lambda p: p.order_ref
        )

    @cached_property
    def renamed_order_of(self) -> dict[str, Order]:
        """Payment ID -> the one order its reference names once normalized, when not exactly."""
        by_normalized = _group(self.orders, lambda o: normalize_reference(o.external_id))
        found = {}
        for p in self.payments:
            if p.order_ref in self.orders_by_id:
                continue
            candidates = by_normalized.get(normalize_reference(p.order_ref), [])
            if len(candidates) == 1:
                found[p.external_id] = candidates[0]
        return found

    @cached_property
    def refunds_by_payment(self) -> dict[str, list[Refund]]:
        return _group(self.refunds, lambda r: r.payment_ref)

    @cached_property
    def fees_by_payment(self) -> dict[str, list[Fee]]:
        return _group(self.fees, lambda f: f.payment_ref)

    @cached_property
    def refund_authorizations(self) -> dict[str, list[Authorization]]:
        refunds = (a for a in self.authorizations if a.subject_kind == "refund")
        return _group(refunds, lambda a: a.subject_ref)

    @cached_property
    def credits(self) -> tuple[BankTransaction, ...]:
        return tuple(b for b in self.bank_transactions if b.direction == "credit")

    @cached_property
    def credits_by_settlement(self) -> dict[str, list[BankTransaction]]:
        """Credits whose description names an existing settlement batch."""
        found = defaultdict(list)
        for credit in self.credits:
            batch = settlement_ref_of(credit)
            if batch in self.settlements_by_id:
                found[batch].append(credit)
        return dict(found)

    @cached_property
    def duplicated_refunds(self) -> list[list[Refund]]:
        """Refunds of the same payment for the same amount, two or more per group."""
        groups = _group(self.refunds, lambda r: (r.payment_ref, r.amount))
        return [g for g in groups.values() if len(g) > 1]

    def order_of(self, payment: Payment) -> Order | None:
        return self.orders_by_id.get(payment.order_ref)

    def batch_members(self, settlement_id: str) -> tuple[list[Payment], list[Refund], list[Fee]]:
        return (
            self._payments_by_batch.get(settlement_id, []),
            self._refunds_by_batch.get(settlement_id, []),
            self._fees_by_batch.get(settlement_id, []),
        )

    @cached_property
    def _payments_by_batch(self) -> dict[str, list[Payment]]:
        return _group(self.payments, lambda p: p.settlement_ref)

    @cached_property
    def _refunds_by_batch(self) -> dict[str, list[Refund]]:
        return _group(self.refunds, lambda r: r.settlement_ref)

    @cached_property
    def _fees_by_batch(self) -> dict[str, list[Fee]]:
        return _group(self.fees, lambda f: f.settlement_ref)


def settlement_ref_of(credit: BankTransaction) -> str | None:
    match = _SETTLEMENT_REF.search(credit.description)
    return match.group() if match else None
