"""What a run produces: balanced match groups and discrepancies with their fingerprints."""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from recon.reconciliation.domain.records import RecordRef
from recon.shared_kernel.money import Money


class DiscrepancyType(StrEnum):
    """The detection catalog of phase 2 (codes of ``ref.discrepancy_types``)."""

    DUPLICATE_PAYMENT = "duplicate_payment"
    UNAUTHORIZED_REFUND = "unauthorized_refund"
    FEE_MISMATCH = "fee_mismatch"
    MISSING_IN_BANK = "missing_in_bank"
    MISSING_IN_GATEWAY = "missing_in_gateway"
    MISSING_IN_ORDERS = "missing_in_orders"
    UNDERPAYMENT = "underpayment"
    OVERPAYMENT = "overpayment"  # amendment 2026-11-10: the mirror of underpayment
    SETTLEMENT_DELAYED = "settlement_delayed"
    AMOUNT_MISMATCH = "amount_mismatch"
    REFERENCE_MISMATCH = "reference_mismatch"
    SEQUENCE_VIOLATION = "sequence_violation"
    DUPLICATE_REFUND = "duplicate_refund"
    SOURCE_CONFLICT = "source_conflict"


@dataclass(frozen=True, slots=True)
class Period:
    """Inclusive date range a run reconciles."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"period ends ({self.end}) before it starts ({self.start})")


@dataclass(frozen=True, slots=True)
class Discrepancy:
    type: DiscrepancyType
    records: frozenset[RecordRef]
    expected: Money
    actual: Money

    def __post_init__(self) -> None:
        if not self.records:
            raise ValueError("a discrepancy involves at least one record")
        if self.expected.currency != self.actual.currency:
            raise ValueError("expected and actual must share one currency")

    @property
    def delta_minor(self) -> int:
        return self.actual.amount_minor - self.expected.amount_minor

    def sort_key(self) -> tuple[str, tuple[RecordRef, ...]]:
        return self.type.value, tuple(sorted(self.records))

    def fingerprint(self, period: Period) -> str:
        """Deterministic over type, records and period, so a re-run finds the same one."""
        canonical = json.dumps(
            [
                self.type.value,
                sorted([r.source.value, r.external_id] for r in self.records),
                period.start.isoformat(),
                period.end.isoformat(),
            ],
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True, order=True)
class MatchMember:
    ref: RecordRef
    role: str


@dataclass(frozen=True, slots=True)
class MatchGroup:
    rule_code: str
    members: frozenset[MatchMember]

    def __post_init__(self) -> None:
        refs = [m.ref for m in self.members]
        if not refs:
            raise ValueError("a match group has at least one member")
        if len(set(refs)) != len(refs):
            raise ValueError("a record appears once in a match group")


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    groups: tuple[MatchGroup, ...]
    discrepancies: tuple[Discrepancy, ...]
