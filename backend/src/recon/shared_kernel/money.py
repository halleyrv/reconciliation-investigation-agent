"""Money as integer minor units plus an ISO 4217 code (ADR-0002)."""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

_CURRENCY = re.compile(r"[A-Z]{3}")
_DECIMAL = re.compile(r"([0-9]+)(?:\.([0-9]{1,2}))?")  # [0-9], not \d: ASCII digits only
# Amounts are stored as BIGINT minor units (ADR-0002).
MAX_MINOR = 2**63 - 1
# shortcut: every v1 currency has 2 minor digits (ADR-0002, single currency); read the exponent
# from ref.currencies when a second currency arrives.
_MINOR_DIGITS = 2


def parse_minor_units(text: str) -> int:
    """Convert a non-negative decimal string such as ``"483.23"`` into minor units, exactly."""
    if type(text) is not str:
        raise TypeError(f"amount must be a decimal string, not {type(text).__name__}")
    match = _DECIMAL.fullmatch(text)
    if match is None:
        raise ValueError(f"amount must be a plain decimal with at most 2 decimals, got {text!r}")
    whole: str = match.group(1)
    fraction: str = match.group(2) or ""
    minor = int(whole + fraction.ljust(_MINOR_DIGITS, "0"))
    if minor > MAX_MINOR:
        raise ValueError(f"amount {text!r} does not fit in 64-bit minor units")
    return minor


def round_to_minor(value: Decimal) -> int:
    """The only rounding in the backend: an intermediate in minor units to an integer, half-even."""
    if type(value) is not Decimal:
        raise TypeError(f"value must be a Decimal, not {type(value).__name__}")
    return int(value.to_integral_value(rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        if type(self.amount_minor) is not int:
            raise TypeError(f"amount_minor must be an int, not {type(self.amount_minor).__name__}")
        if not -MAX_MINOR <= self.amount_minor <= MAX_MINOR:
            raise ValueError(f"amount_minor {self.amount_minor} does not fit in 64 bits")
        if not isinstance(self.currency, str) or not _CURRENCY.fullmatch(self.currency):
            raise ValueError(f"currency must be an ISO 4217 code, got {self.currency!r}")

    @classmethod
    def from_decimal_string(cls, text: str, currency: str) -> Money:
        return cls(parse_minor_units(text), currency)
