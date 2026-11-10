"""The operator's reference file: fee schedules and holidays transcribed from the gateway policy."""

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from recon.reconciliation.domain.fees import FeeSchedule
from recon.shared_kernel.money import Money


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class _Schedule(_Strict):
    gateway: str
    # shortcut: the seeded ref values; read ref.fee_types and ref.currencies when they grow.
    fee_type: Literal["processing"]
    rate_bps: int
    fixed: str  # decimal string, like every amount the sources send
    currency: Literal["USD"]
    valid_from: date
    valid_until: date | None


class _ReferenceFile(_Strict):
    fee_schedules: list[_Schedule]
    calendar_years: list[int]  # years the holiday list is complete for
    holidays: list[date]


def read_reference_file(
    path: Path,
) -> tuple[tuple[FeeSchedule, ...], frozenset[date], frozenset[int]]:
    """Raises ``ValueError`` naming the field when the file does not match the format."""
    parsed = _ReferenceFile.model_validate_json(path.read_bytes())
    schedules = tuple(
        FeeSchedule(
            s.gateway,
            s.fee_type,
            s.rate_bps,
            Money.from_decimal_string(s.fixed, s.currency),
            s.valid_from,
            s.valid_until,
        )
        for s in parsed.fee_schedules
    )
    years = frozenset(parsed.calendar_years)
    outside = sorted(d for d in parsed.holidays if d.year not in years)
    if outside:
        raise ValueError(f"holidays outside calendar_years: {', '.join(map(str, outside))}")
    return schedules, frozenset(parsed.holidays), years
