"""The evaluation report an operator reads (AC-2b.2), as Markdown."""

from recon.reconciliation.application.evaluation import Evaluation, Finding
from recon.reconciliation.domain.run import ReconciliationRun


def _pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate:.1%}"


def _finding(f: Finding) -> str:
    records = ", ".join(f"{source}/{external_id}" for source, external_id in sorted(f.records))
    return f"`{f.type}` delta {f.delta_minor}: {records}"


def _section(title: str, lines: list[str]) -> list[str]:
    return [f"## {title}", "", *([f"- {line}" for line in lines] or ["None."]), ""]


def render_report(run: ReconciliationRun, evaluation: Evaluation, ground_truth: str) -> str:
    verdict = "PASS" if evaluation.perfect else "FAIL"
    lines = [
        "# Reconciliation evaluation",
        "",
        f"- Run: `{run.id}`, ruleset `{run.ruleset_version}`,"
        f" period {run.period.start} to {run.period.end}",
        f"- Ground truth: `{ground_truth}`",
        f"- Result: **{verdict}**",
        "",
        "## Discrepancies per type",
        "",
        "| Type | Expected | Detected | Matched | Precision | Recall |",
        "|------|----------|----------|---------|-----------|--------|",
        *(
            f"| `{s.type}` | {s.expected} | {s.detected} | {s.matched}"
            f" | {_pct(s.precision)} | {_pct(s.recall)} |"
            for s in evaluation.types
        ),
        "",
        "## Clean links",
        "",
        "| Expected | Found | Matched | Precision | Recall |",
        "|----------|-------|---------|-----------|--------|",
        f"| {evaluation.links_expected} | {evaluation.links_found} | {evaluation.links_matched}"
        f" | {_pct(evaluation.link_precision)} | {_pct(evaluation.link_recall)} |",
        "",
    ]
    lines += _section(
        "Delta mismatches",
        [f"{_finding(f)}; detected {delta}" for f, delta in evaluation.delta_mismatches],
    )
    lines += _section("Missed discrepancies", [_finding(f) for f in evaluation.missed])
    lines += _section("Unexpected discrepancies", [_finding(f) for f in evaluation.unexpected])
    lines += _section("Missed links", [str(link) for link in evaluation.missed_links])
    lines += _section("Unexpected links", [str(link) for link in evaluation.unexpected_links])
    return "\n".join(lines)
