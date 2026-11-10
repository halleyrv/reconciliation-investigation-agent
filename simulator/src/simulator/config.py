"""Simulator configuration: loaded from YAML, validated, money kept as Decimal."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

ANOMALY_TYPES = (
    "duplicate_payment",
    "unauthorized_refund",
    "incorrect_fee",
    "missing_transaction",
    "partial_payment",
    "delayed_settlement",
    "incorrect_amount",
    "inconsistent_reference",
    "out_of_order_event",
    "duplicate_refund",
    "conflicting_resent_record",
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class GatewayFees:
    percentage_bps: int
    fixed_fee: Decimal


@dataclass(frozen=True)
class Config:
    orders: int
    period_start: date
    period_end: date
    currency: str
    gateways: dict[str, GatewayFees]
    settlement_lag_business_days: int
    holidays: tuple[date, ...]
    refund_rate: Decimal
    anomaly_rates: dict[str, Decimal]

    def to_dict(self) -> dict[str, Any]:
        """Canonical, JSON-ready form. Money and rates stay decimal strings."""
        return {
            "orders": self.orders,
            "period": {"start": self.period_start.isoformat(), "end": self.period_end.isoformat()},
            "currency": self.currency,
            "gateways": {
                name: {"percentage_bps": g.percentage_bps, "fixed_fee": str(g.fixed_fee)}
                for name, g in sorted(self.gateways.items())
            },
            "settlement_lag_business_days": self.settlement_lag_business_days,
            "holidays": [h.isoformat() for h in self.holidays],
            "refund_rate": str(self.refund_rate),
            "anomaly_rates": {k: str(v) for k, v in self.anomaly_rates.items()},
        }


def _decimal(value: Any, name: str) -> Decimal:
    # Floats are rejected: YAML 0.1 would already be inexact before we see it.
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be a quoted decimal string, got {value!r}")
    try:
        return Decimal(value)
    except InvalidOperation:
        raise ConfigError(f"{name} is not a decimal: {value!r}") from None


def _rate(value: Any, name: str) -> Decimal:
    rate = _decimal(value, name)
    if not Decimal(0) <= rate <= Decimal(1):
        raise ConfigError(f"{name} must be between 0 and 1, got {value}")
    return rate


def _int(value: Any, name: str, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ConfigError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return value


def _holidays(value: Any) -> tuple[date, ...]:
    if value is None:  # absent, or an empty YAML key
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"holidays must be a list of dates, got {value!r}")
    try:
        return tuple(sorted({date.fromisoformat(str(day)) for day in value}))
    except ValueError:
        raise ConfigError(f"holidays must be ISO dates (YYYY-MM-DD), got {value!r}") from None


def parse_config(raw: Any) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")
    try:
        period = raw["period"]
        start = date.fromisoformat(str(period["start"]))
        end = date.fromisoformat(str(period["end"]))
        gateways = {
            str(name): GatewayFees(
                percentage_bps=_int(g["percentage_bps"], f"{name}.percentage_bps", 0),
                fixed_fee=_decimal(g["fixed_fee"], f"{name}.fixed_fee"),
            )
            for name, g in raw["gateways"].items()
        }
        rates = raw.get("anomaly_rates", {})
        unknown = sorted(set(rates) - set(ANOMALY_TYPES))
        if unknown:
            raise ConfigError(f"unknown anomaly types: {', '.join(unknown)}")
        config = Config(
            orders=_int(raw["orders"], "orders", 1),
            period_start=start,
            period_end=end,
            currency=str(raw["currency"]),
            gateways=gateways,
            settlement_lag_business_days=_int(
                raw["settlement_lag_business_days"], "settlement_lag_business_days", 0
            ),
            holidays=_holidays(raw.get("holidays")),
            refund_rate=_rate(raw["refund_rate"], "refund_rate"),
            anomaly_rates={
                t: _rate(rates.get(t, "0"), f"anomaly_rates.{t}") for t in ANOMALY_TYPES
            },
        )
    except (KeyError, TypeError, AttributeError) as error:
        raise ConfigError(f"missing or malformed config field: {error}") from None
    except ValueError as error:
        if isinstance(error, ConfigError):
            raise
        raise ConfigError(str(error)) from None
    if end < start:
        raise ConfigError("period.end is before period.start")
    if not gateways:
        raise ConfigError("at least one gateway is required")
    return config


def load_config(path: Path) -> Config:
    return parse_config(yaml.safe_load(path.read_text(encoding="utf-8")))
