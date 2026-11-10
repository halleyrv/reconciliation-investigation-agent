"""The MatchingEngine: runs every registered rule, then links the batches nothing disputes."""

from collections.abc import Sequence

from recon.reconciliation.domain.records import Payment, RecordRef
from recon.reconciliation.domain.results import (
    Discrepancy,
    MatchGroup,
    MatchMember,
    ReconciliationResult,
)
from recon.reconciliation.domain.rules import CATALOG, MatchRule, Ruleset
from recon.reconciliation.domain.snapshot import Snapshot

SETTLEMENT_BATCH = "settlement_batch"


class MatchingEngine:
    def __init__(self, rules: Sequence[MatchRule]) -> None:
        self._rules = tuple(rules)

    def run(self, snapshot: Snapshot, ruleset: Ruleset) -> ReconciliationResult:
        found = [d for rule in self._rules for d in rule.detect(snapshot, ruleset)]
        keys = [d.sort_key() for d in found]
        if len(set(keys)) != len(keys):
            raise ValueError("two rules reported the same discrepancy")
        discrepancies = tuple(sorted(found, key=Discrepancy.sort_key))
        disputed = {r for d in discrepancies for r in d.records}
        return ReconciliationResult(_link_batches(snapshot, disputed), discrepancies)


def default_engine() -> MatchingEngine:
    return MatchingEngine(CATALOG)


def _link_batches(snapshot: Snapshot, disputed: set[RecordRef]) -> tuple[MatchGroup, ...]:
    """One group per undisputed batch paid out once: settlement, payout and every member.

    Many-to-one matching: the batch's payments minus its refunds and fees equal the declared
    net and the bank credit. An order joins its payment's group only when nothing about the
    order, its payment, fees or refunds is disputed, which is its clean link.
    """
    groups = []
    for s in sorted(snapshot.settlements, key=lambda s: s.external_id):
        credits = snapshot.credits_by_settlement.get(s.external_id, [])
        if s.ref in disputed or len(credits) != 1 or credits[0].ref in disputed:
            continue
        payments, refunds, fees = snapshot.batch_members(s.external_id)
        net = (
            sum(p.amount.amount_minor for p in payments)
            - sum(r.amount.amount_minor for r in refunds)
            - sum(f.amount.amount_minor for f in fees)
        )
        if not net == s.net_amount.amount_minor == credits[0].amount.amount_minor:
            continue  # a rule reports it; never link an unbalanced batch
        members = {MatchMember(s.ref, "settlement"), MatchMember(credits[0].ref, "payout")}
        members |= {MatchMember(p.ref, "payment") for p in payments}
        members |= {MatchMember(r.ref, "refund") for r in refunds}
        members |= {MatchMember(f.ref, "fee") for f in fees}
        for p in payments:
            order = snapshot.order_of(p)
            if order is not None and _clean_chain(snapshot, order.ref, p, disputed):
                members.add(MatchMember(order.ref, "order"))
        groups.append(MatchGroup(SETTLEMENT_BATCH, frozenset(members)))
    return tuple(groups)


def _clean_chain(
    snapshot: Snapshot, order: RecordRef, payment: Payment, disputed: set[RecordRef]
) -> bool:
    chain = {
        order,
        payment.ref,
        *(f.ref for f in snapshot.fees_by_payment.get(payment.external_id, [])),
        *(r.ref for r in snapshot.refunds_by_payment.get(payment.external_id, [])),
    }
    return not chain & disputed and len(snapshot.payments_by_order[order.external_id]) == 1
