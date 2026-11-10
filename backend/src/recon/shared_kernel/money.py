"""Money as integer minor units plus an ISO 4217 code (ADR-0002)."""

import re
from dataclasses import dataclass

_CURRENCY = re.compile(r"[A-Z]{3}")
_DECIMAL = re.compile(r"(\d+)(?:\.(\d{1,2}))?")
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
    return int(whole + fraction.ljust(_MINOR_DIGITS, "0"))


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        if type(self.amount_minor) is not int:
            raise TypeError(f"amount_minor must be an int, not {type(self.amount_minor).__name__}")
        if not isinstance(self.currency, str) or not _CURRENCY.fullmatch(self.currency):
            raise ValueError(f"currency must be an ISO 4217 code, got {self.currency!r}")

    @classmethod
    def from_decimal_string(cls, text: str, currency: str) -> Money:
        return cls(parse_minor_units(text), currency)
