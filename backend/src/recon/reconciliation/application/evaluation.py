"""Scoring a run against a known answer (AC-2b.2): pure set arithmetic, no I/O.

A detected discrepancy matches an expected one when type and record set are equal
(assumption B2); its delta is then compared separately (AC-2b.4).
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

type RecordKey = tuple[str, str]  # (source, external_id)


@dataclass(frozen=True, slots=True)
class Finding:
    type: str
    records: frozenset[RecordKey]
    delta_minor: int

    @property
    def key(self) -> tuple[str, frozenset[RecordKey]]:
        return self.type, self.records


@dataclass(frozen=True, slots=True, order=True)
class Link:
    order_id: str
    payment_id: str
    settlement_id: str
    bank_transaction_id: str


def _rate(hits: int, total: int) -> float | None:
    return hits / total if total else None


@dataclass(frozen=True, slots=True)
class TypeScore:
    type: str
    expected: int
    detected: int
    matched: int

    @property
    def precision(self) -> float | None:
        return _rate(self.matched, self.detected)

    @property
    def recall(self) -> float | None:
        return _rate(self.matched, self.expected)


@dataclass(frozen=True, slots=True)
class Evaluation:
    types: tuple[TypeScore, ...]
    missed: tuple[Finding, ...]
    unexpected: tuple[Finding, ...]
    delta_mismatches: tuple[tuple[Finding, int], ...]  # (expected, detected delta)
    links_expected: int
    links_found: int
    links_matched: int
    missed_links: tuple[Link, ...]
    unexpected_links: tuple[Link, ...]

    @property
    def link_precision(self) -> float | None:
        return _rate(self.links_matched, self.links_found)

    @property
    def link_recall(self) -> float | None:
        return _rate(self.links_matched, self.links_expected)

    @property
    def perfect(self) -> bool:
        return not (
            self.missed
            or self.unexpected
            or self.delta_mismatches
            or self.missed_links
            or self.unexpected_links
        )


def _order(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    return tuple(sorted(findings, key=lambda f: (f.type, sorted(f.records))))


def evaluate(
    expected: Iterable[Finding],
    detected: Iterable[Finding],
    expected_links: set[Link],
    found_links: set[Link],
) -> Evaluation:
    want = {f.key: f for f in expected}
    got = {f.key: f for f in detected}
    matched = want.keys() & got.keys()
    wanted, found, hit = (Counter(t for t, _ in keys) for keys in (want, got, matched))
    types = tuple(
        TypeScore(t, wanted[t], found[t], hit[t]) for t in sorted(wanted.keys() | found.keys())
    )
    mismatches = tuple(
        (want[k], got[k].delta_minor)
        for k in sorted(matched, key=lambda k: (k[0], sorted(k[1])))
        if want[k].delta_minor != got[k].delta_minor
    )
    return Evaluation(
        types=types,
        missed=_order(want[k] for k in want.keys() - matched),
        unexpected=_order(got[k] for k in got.keys() - matched),
        delta_mismatches=mismatches,
        links_expected=len(expected_links),
        links_found=len(found_links),
        links_matched=len(expected_links & found_links),
        missed_links=tuple(sorted(expected_links - found_links)),
        unexpected_links=tuple(sorted(found_links - expected_links)),
    )
