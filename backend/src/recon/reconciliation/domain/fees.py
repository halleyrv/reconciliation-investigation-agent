"""Fee schedules: what a gateway charges, loaded by an operator (OD1), never parsed by an LLM."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from recon.shared_kernel.money import Money, round_to_minor


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    gateway: str
    fee_type: str
    rate_bps: int
    fixed: Money
    valid_from: date
    valid_until: date | None  # exclusive; None is open-ended

    def __post_init__(self) -> None:
        if type(self.rate_bps) is not int or self.rate_bps < 0:
            raise ValueError(f"rate_bps must be a non-negative int, got {self.rate_bps!r}")
        if self.fixed.amount_minor < 0:
            raise ValueError("fixed fee must not be negative")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")

    def applies_to(self, gateway: str, fee_type: str, day: date) -> bool:
        return (
            gateway == self.gateway
            and fee_type == self.fee_type
            and self.valid_from <= day
            and (self.valid_until is None or day < self.valid_until)
        )

    def fee_for(self, amount: Money) -> Money:
        if amount.currency != self.fixed.currency:
            raise ValueError(
                f"fee schedule is in {self.fixed.currency}, amount in {amount.currency}"
            )
        exact = Decimal(amount.amount_minor) * self.rate_bps / 10_000 + self.fixed.amount_minor
        return Money(round_to_minor(exact), amount.currency)
