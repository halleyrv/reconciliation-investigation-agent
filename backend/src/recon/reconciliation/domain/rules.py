"""One matching rule per row of the detection catalog (phase 2), registered in the engine.

Each rule reports one discrepancy per root cause (assumption B1). Where two rules could see
the same symptom, the more general one skips what the specific one owns, so rules never
depend on the order they run in.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from recon.reconciliation.domain.calendar import BusinessCalendar
from recon.reconciliation.domain.fees import FeeSchedule
from recon.reconciliation.domain.records import Authorization, Fee, Payment, RecordRef, Refund
from recon.reconciliation.domain.results import Discrepancy, DiscrepancyType
from recon.reconciliation.domain.snapshot import Snapshot, settlement_ref_of
from recon.shared_kernel.money import Money

T = DiscrepancyType


@dataclass(frozen=True, slots=True)
class Ruleset:
    fee_schedules: tuple[FeeSchedule, ...]
    calendar: BusinessCalendar
    settlement_lag_business_days: int

    def schedule_for(self, gateway: str, fee_type: str, day: date) -> FeeSchedule | None:
        return next((s for s in self.fee_schedules if s.applies_to(gateway, fee_type, day)), None)


class MatchRule(Protocol):
    def detect(self, snapshot: Snapshot, ruleset: Ruleset) -> Iterable[Discrepancy]: ...


def _no_impact(kind: DiscrepancyType, refs: Iterable[RecordRef], currency: str) -> Discrepancy:
    return Discrepancy(kind, frozenset(refs), Money(0, currency), Money(0, currency))


def _with_order(snapshot: Snapshot, payment: Payment | None) -> list[RecordRef]:
    if payment is None:
        return []
    order = snapshot.order_of(payment)
    return [payment.ref] if order is None else [order.ref, payment.ref]


class DuplicatePaymentRule:
    """#1: two or more payments claim the same order with the same amount."""

    def detect(self, snapshot: Snapshot, ruleset: Ruleset) -> Iterator[Discrepancy]:
        for order_id, payments in snapshot.payments_by_order.items():
            by_amount: dict[Money, list[Payment]] = {}
            for p in payments:
                by_amount.setdefault(p.amount, []).append(p)
            for amount, copies in by_amount.items():
                if len(copies) > 1:
                    refs = [snapshot.orders_by_id[order_id].ref, *(p.ref for p in copies)]
                    actual = Money(amount.amount_minor * len(copies), amount.currency)
                    yield Discrepancy(T.DUPLICATE_PAYMENT, frozenset(refs), amount, actual)


class UnauthorizedRefundRule:
    """#2: no authorization covers the refund's amount and was approved before it."""

    def detect(self, snapshot: Snapshot, ruleset: Ruleset) -> Iterator[Discrepancy]:
        duplicated = {r.external_id for group in snapshot.duplicated_refunds for r in group}
        for refund in snapshot.refunds:
            if refund.external_id in duplicated:  # owned by DuplicateRefundRule
                continue
            authorizations = snapshot.refund_authorizations.get(refund.external_id, [])
            if any(_covers(a, refund) for a in authorizations):
                continue
            payment = snapshot.payments_by_id.get(refund.payment_ref)
            refs = [refund.ref, *(a.ref for a in authorizations), *_with_order(snapshot, payment)]
            currency = refund.amount.currency
            yield Discrepancy(
                T.UNAUTHORIZED_REFUND,
                frozenset(refs),
                Money(0, currency),
                Money(-refund.amount.amount_minor, currency),
            )


def _covers(authorization: Authorization, refund: Refund) -> bool:
    return (
        authorization.approved_at < refund.refunded_at
        and authorization.max_amount.amount_minor >= refund.amount.amount_minor
    )


class FeeMismatchRule:
    """#3: the fee differs from the schedule applied to its payment."""

    def detect(self, snapshot: Snapshot, ruleset: Ruleset) -> Iterator[Discrepancy]:
        for fee in snapshot.fees:
            payment = snapshot.payments_by_id.get(fee.payment_ref)
            if payment is None:  # a dangling reference, owned by ReferenceMismatchRule
                continue
            schedule = ruleset.schedule_for(fee.gateway, fee.fee_type, payment.captured_at.date())
            # shortcut: a fee with no loaded schedule is not checked; report it as a
            # discrepancy type of its own if operators ask for it.
            if schedule is None:
                continue
            expected = schedule.fee_for(payment.amount)
            if expected != fee.amount:
                refs = frozenset({payment.ref, fee.ref})
                yield Discrepancy(T.FEE_MISMATCH, refs, expected, fee.amount)


class MissingTransactionRule:
    """#4: a record with no counterpart in the other source, one code per direction."""

    def detect(self, snapshot: Snapshot, ruleset: Ruleset) -> Iterator[Discrepancy]:
        currency = snapshot.currency
        renamed = snapshot.renamed_order_of
        for p in snapshot.payments:
            if snapshot.order_of(p) is None and p.external_id not in renamed:
                fees = snapshot.fees_by_payment.get(p.external_id, [])
                refs = frozenset({p.ref, *(f.ref for f in fees)})
                yield Discrepancy(T.MISSING_IN_ORDERS, refs, Money(0, currency), p.amount)
        reached = {o.external_id for o in renamed.values()}
        for order in snapshot.orders:
            if (
                order.external_id not in snapshot.payments_by_order
                and order.external_id not in reached
            ):
                yield Discrepancy(
                    T.MISSING_IN_GATEWAY, frozenset({order.ref}), order.total, Money(0, currency)
                )
        for credit in snapshot.credits:
            if settlement_ref_of(credit) not in snapshot.settlements_by_id:
                refs = frozenset({credit.ref})
                yield Discrepancy(T.MISSING_IN_GATEWAY, refs, Money(0, currency), credit.amount)
        for s in snapshot.settlements:
            if s.external_id not in snapshot.credits_by_settlement:
                refs = frozenset({s.ref})
                yield Discrepancy(T.MISSING_IN_BANK, refs, s.net_amount, Money(0, currency))


class UnderpaymentRule:
    """#5: the order's only payment is below its total."""

    def detect(self, snapshot: Snapshot, ruleset: Ruleset) -> Iterator[Discrepancy]:
        for order_id, payments in snapshot.payments_by_order.items():
            order = snapshot.orders_by_id[order_id]
            if len(payments) == 1 and payments[0].amount.amount_minor < order.total.amount_minor:
                refs = frozenset({order.ref, payments[0].ref})
                yield Discrepancy(T.UNDERPAYMENT, refs, order.total, payments[0].amount)


class SettlementDelayedRule:
    """#6: the bank credit is later than batch date + the settlement lag in business days."""

    def detect(self, snapshot: Snapshot, ruleset: Ruleset) -> Iterator[Discrepancy]:
        for batch, credits in snapshot.credits_by_settlement.items():
            settlement = snapshot.settlements_by_id[batch]
            due = ruleset.calendar.add_business_days(
                settlement.batch_date, ruleset.settlement_lag_business_days
            )
            for credit in credits:
                if credit.value_date > due:
                    refs = (settlement.ref, credit.ref)
                    yield _no_impact(T.SETTLEMENT_DELAYED, refs, snapshot.currency)


class AmountMismatchRule:
    """#7: the bank credit differs from the declared net, or the net from its members."""

    def detect(self, snapshot: Snapshot, ruleset: Ruleset) -> Iterator[Discrepancy]:
        currency = snapshot.currency
        for s in snapshot.settlements:
            payments, refunds, fees = snapshot.batch_members(s.external_id)
            members_net = (
                sum(p.amount.amount_minor for p in payments)
                - sum(r.amount.amount_minor for r in refunds)
                - sum(f.amount.amount_minor for f in fees)
            )
            if members_net != s.net_amount.amount_minor:
                refs = frozenset({s.ref})
                yield Discrepancy(
                    T.AMOUNT_MISMATCH, refs, Money(members_net, currency), s.net_amount
                )
            credits = snapshot.credits_by_settlement.get(s.external_id, [])
            paid = sum(c.amount.amount_minor for c in credits)
            if credits and paid != s.net_amount.amount_minor:
                refs = frozenset({s.ref, *(c.ref for c in credits)})
                yield Discrepancy(T.AMOUNT_MISMATCH, refs, s.net_amount, Money(paid, currency))


class ReferenceMismatchRule:
    """#8: a reference that resolves only once normalized, or to no record at all."""

    def detect(self, snapshot: Snapshot, ruleset: Ruleset) -> Iterator[Discrepancy]:
        currency = snapshot.currency
        payments = snapshot.payments_by_id
        batches = snapshot.settlements_by_id
        for payment_id, order in snapshot.renamed_order_of.items():
            refs = (order.ref, payments[payment_id].ref)
            yield _no_impact(T.REFERENCE_MISMATCH, refs, currency)
        children: tuple[Refund | Fee, ...] = (*snapshot.refunds, *snapshot.fees)
        for child in children:
            if child.payment_ref not in payments:
                yield _no_impact(T.REFERENCE_MISMATCH, (child.ref,), currency)
        for member in (*snapshot.payments, *children):
            if member.settlement_ref not in batches:
                yield _no_impact(T.REFERENCE_MISMATCH, (member.ref,), currency)


class SequenceViolationRule:
    """#9: order <= payment <= settlement <= value date, and refund after payment."""

    def detect(self, snapshot: Snapshot, ruleset: Ruleset) -> Iterator[Discrepancy]:
        currency = snapshot.currency
        batches = snapshot.settlements_by_id
        for p in snapshot.payments:
            order = snapshot.order_of(p)
            if order is not None and order.placed_at > p.captured_at:
                yield _no_impact(T.SEQUENCE_VIOLATION, (order.ref, p.ref), currency)
            batch = batches.get(p.settlement_ref)
            if batch is not None and p.captured_at.date() > batch.batch_date:
                yield _no_impact(T.SEQUENCE_VIOLATION, (p.ref, batch.ref), currency)
        for batch_id, credits in snapshot.credits_by_settlement.items():
            batch = batches[batch_id]
            for credit in credits:
                if credit.value_date < batch.batch_date:
                    yield _no_impact(T.SEQUENCE_VIOLATION, (batch.ref, credit.ref), currency)
        for refund in snapshot.refunds:
            paid = snapshot.payments_by_id.get(refund.payment_ref)
            if paid is not None and refund.refunded_at <= paid.captured_at:
                yield _no_impact(T.SEQUENCE_VIOLATION, (paid.ref, refund.ref), currency)


class DuplicateRefundRule:
    """#10: two or more refunds of the same payment for the same amount."""

    def detect(self, snapshot: Snapshot, ruleset: Ruleset) -> Iterator[Discrepancy]:
        for copies in snapshot.duplicated_refunds:
            first = copies[0]
            payment = snapshot.payments_by_id.get(first.payment_ref)
            authorizations = [
                a for r in copies for a in snapshot.refund_authorizations.get(r.external_id, [])
            ]
            refs = [
                *(r.ref for r in copies),
                *(a.ref for a in authorizations),
                *_with_order(snapshot, payment),
            ]
            one, currency = first.amount.amount_minor, first.amount.currency
            yield Discrepancy(
                T.DUPLICATE_REFUND,
                frozenset(refs),
                Money(-one, currency),
                Money(-one * len(copies), currency),
            )


class SourceConflictRule:
    """#11: a source re-sent a known record with a different payload (from Ingestion)."""

    def detect(self, snapshot: Snapshot, ruleset: Ruleset) -> Iterator[Discrepancy]:
        for conflicted in sorted({c.ref for c in snapshot.conflicts}):
            yield _no_impact(T.SOURCE_CONFLICT, (conflicted,), snapshot.currency)


CATALOG: tuple[MatchRule, ...] = (
    DuplicatePaymentRule(),
    UnauthorizedRefundRule(),
    FeeMismatchRule(),
    MissingTransactionRule(),
    UnderpaymentRule(),
    SettlementDelayedRule(),
    AmountMismatchRule(),
    ReferenceMismatchRule(),
    SequenceViolationRule(),
    DuplicateRefundRule(),
    SourceConflictRule(),
)
