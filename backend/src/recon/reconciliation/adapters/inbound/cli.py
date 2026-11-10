"""``recon-reference``: an operator loads the fee schedules and holidays the engine applies."""

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from recon.reconciliation.adapters.inbound.reference_file import read_reference_file
from recon.reconciliation.application.load_reference_data import (
    LoadReferenceData,
    ReferenceDataConflict,
)


def run_reference(argv: Sequence[str] | None, load: Callable[[], LoadReferenceData]) -> int:
    """Exit codes: 0 loaded (or already loaded), 1 conflicts with loaded data, 2 bad file."""
    parser = argparse.ArgumentParser(
        prog="recon-reference",
        description="Load fee schedules and bank holidays from a reference JSON file.",
    )
    parser.add_argument(
        "file", type=Path, help="reference file, e.g. reference/gateway-policy-2026.json"
    )
    args = parser.parse_args(argv)
    try:
        schedules, holidays = read_reference_file(args.file)
    except (ValueError, OSError) as exc:
        print(f"recon-reference: nothing loaded: {exc}", file=sys.stderr)
        return 2
    try:
        result = load()(schedules, holidays)
    except ReferenceDataConflict as exc:
        print(f"recon-reference: nothing loaded: {exc}", file=sys.stderr)
        return 1
    known_schedules = len(set(schedules)) - result.schedules_added
    print(f"fee schedules: {result.schedules_added} added, {known_schedules} already loaded")
    known_holidays = len(holidays) - result.holidays_added
    print(f"holidays: {result.holidays_added} added, {known_holidays} already loaded")
    return 0
