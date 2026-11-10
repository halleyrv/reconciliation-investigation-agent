"""Operator commands: ``recon-reference``, ``recon-reconcile`` and ``recon-evaluate``."""

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from recon.reconciliation.adapters.inbound.ground_truth import read_ground_truth
from recon.reconciliation.adapters.inbound.reference_file import read_reference_file
from recon.reconciliation.adapters.inbound.report import render_report
from recon.reconciliation.application.evaluate_run import EvaluateRun, NoCompletedRun
from recon.reconciliation.application.load_reference_data import (
    LoadReferenceData,
    ReferenceDataConflict,
)
from recon.reconciliation.application.reconcile_period import (
    RULESET_VERSION,
    ReconcilePeriod,
    RunFailed,
)
from recon.reconciliation.domain.results import Period


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
        schedules, holidays, years = read_reference_file(args.file)
    except (ValueError, OSError) as exc:
        print(f"recon-reference: nothing loaded: {exc}", file=sys.stderr)
        return 2
    try:
        result = load()(schedules, holidays, years)
    except ReferenceDataConflict as exc:
        print(f"recon-reference: nothing loaded: {exc}", file=sys.stderr)
        return 1
    known_schedules = len(set(schedules)) - result.schedules_added
    print(f"fee schedules: {result.schedules_added} added, {known_schedules} already loaded")
    known_holidays = len(holidays) - result.holidays_added
    print(f"holidays: {result.holidays_added} added, {known_holidays} already loaded")
    known_years = len(years) - result.years_added
    print(f"calendar years: {result.years_added} added, {known_years} already loaded")
    return 0


def _period(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    parser.add_argument("--ruleset", default=RULESET_VERSION, help="ruleset version (default v1)")


def run_reconcile(argv: Sequence[str] | None, reconcile: Callable[[], ReconcilePeriod]) -> int:
    """Exit codes: 0 completed (or already completed), 1 the run failed, 2 nothing was run."""
    parser = argparse.ArgumentParser(
        prog="recon-reconcile", description="Reconcile a period (inclusive dates)."
    )
    _period(parser)
    args = parser.parse_args(argv)
    try:
        period = Period(args.start, args.end)
        run = reconcile()(period, args.ruleset)
    except RunFailed as exc:  # recorded as failed with no output; a new call may retry
        print(f"recon-reconcile: {exc}", file=sys.stderr)
        for note in getattr(exc, "__notes__", []):  # e.g. it could not be marked failed
            print(f"recon-reconcile: {note}", file=sys.stderr)
        return 1
    except Exception as exc:  # no run was started: bad period, overlap, unreachable database
        print(f"recon-reconcile: nothing run: {exc}", file=sys.stderr)
        return 2
    print(f"run {run.id} ({run.ruleset_version}, {period.start} to {period.end}): {run.status}")
    return 0


def run_evaluate(argv: Sequence[str] | None, evaluate_run: Callable[[], EvaluateRun]) -> int:
    """Exit codes: 0 everything matched, 1 a report with misses, 2 nothing was evaluated."""
    parser = argparse.ArgumentParser(
        prog="recon-evaluate",
        description="Score the completed run of a period against an export's ground_truth.json.",
    )
    parser.add_argument("directory", type=Path, help="simulator export with ground_truth.json")
    _period(parser)
    parser.add_argument("--report", type=Path, required=True, help="Markdown report to write")
    args = parser.parse_args(argv)
    truth = args.directory / "ground_truth.json"
    try:
        expected, links = read_ground_truth(truth)
        run, evaluation = evaluate_run()(
            Period(args.start, args.end), expected, links, args.ruleset
        )
        args.report.write_text(render_report(run, evaluation, str(truth)) + "\n")
    except (ValueError, KeyError, OSError, NoCompletedRun) as exc:
        print(f"recon-evaluate: nothing evaluated: {exc}", file=sys.stderr)
        return 2
    scores = evaluation.types
    print(
        f"discrepancies: {sum(s.expected for s in scores)} expected,"
        f" {sum(s.detected for s in scores)} detected, {sum(s.matched for s in scores)} matched"
    )
    print(
        f"links: {evaluation.links_expected} expected, {evaluation.links_found} found,"
        f" {evaluation.links_matched} matched"
    )
    print(f"delta mismatches: {len(evaluation.delta_mismatches)}")
    print(f"report: {args.report} ({'PASS' if evaluation.perfect else 'FAIL'})")
    return 0 if evaluation.perfect else 1
