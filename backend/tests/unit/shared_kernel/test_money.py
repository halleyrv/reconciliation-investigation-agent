from decimal import Decimal

import pytest

from recon.shared_kernel.money import Money, round_to_minor


def test_decimal_strings_convert_to_exact_minor_units() -> None:
    assert Money.from_decimal_string("483.23", "USD") == Money(48323, "USD")
    assert Money.from_decimal_string("0.05", "USD") == Money(5, "USD")
    assert Money.from_decimal_string("12.5", "USD") == Money(1250, "USD")
    assert Money.from_decimal_string("7", "USD") == Money(700, "USD")


@pytest.mark.parametrize(
    "text", ["1.234", "0.001", "1e2", "-1.00", "", " 1.00", "1,00", "NaN", "١٢.٣٤"]
)
def test_decimal_strings_that_are_not_plain_two_place_amounts_are_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="at most 2 decimals"):
        Money.from_decimal_string(text, "USD")


@pytest.mark.parametrize("value", [12.5, 1250.0, Decimal("1250.5"), Decimal("1250"), True, None])
def test_money_rejects_anything_but_an_int_and_a_string_amount(value: object) -> None:
    with pytest.raises(TypeError):
        Money(value, "USD")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money.from_decimal_string(value, "USD")  # type: ignore[arg-type]


def test_money_rejects_a_malformed_currency() -> None:
    with pytest.raises(ValueError, match="currency"):
        Money(100, "usd")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0.5"), 0),
        (Decimal("1.5"), 2),
        (Decimal("2.5"), 2),
        (Decimal("-2.5"), -2),
        (Decimal("2.5000001"), 3),
        (Decimal("1427.47"), 1427),
        (Decimal("7"), 7),
    ],
)
def test_round_to_minor_rounds_once_half_even(value: Decimal, expected: int) -> None:
    rounded = round_to_minor(value)
    assert rounded == expected
    assert type(rounded) is int


@pytest.mark.parametrize("value", [2.5, 2, "2.5"])
def test_round_to_minor_accepts_only_a_decimal(value: object) -> None:
    with pytest.raises(TypeError):
        round_to_minor(value)  # type: ignore[arg-type]
