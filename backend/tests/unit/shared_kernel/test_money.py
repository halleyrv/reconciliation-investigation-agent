import pytest

from recon.shared_kernel.money import Money


def test_decimal_strings_convert_to_exact_minor_units() -> None:
    assert Money.from_decimal_string("483.23", "USD") == Money(48323, "USD")
    assert Money.from_decimal_string("0.05", "USD") == Money(5, "USD")
    assert Money.from_decimal_string("12.5", "USD") == Money(1250, "USD")
    assert Money.from_decimal_string("7", "USD") == Money(700, "USD")


@pytest.mark.parametrize("text", ["1.234", "0.001", "1e2", "-1.00", "", " 1.00", "1,00", "NaN"])
def test_decimal_strings_that_are_not_plain_two_place_amounts_are_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="at most 2 decimals"):
        Money.from_decimal_string(text, "USD")


@pytest.mark.parametrize("value", [12.5, 1250.0, True, None])
def test_money_rejects_anything_but_an_int_and_a_string_amount(value: object) -> None:
    with pytest.raises(TypeError):
        Money(value, "USD")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money.from_decimal_string(value, "USD")  # type: ignore[arg-type]


def test_money_rejects_a_malformed_currency() -> None:
    with pytest.raises(ValueError, match="currency"):
        Money(100, "usd")
