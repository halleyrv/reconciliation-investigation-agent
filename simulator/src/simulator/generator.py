"""Generate one dataset: clean records, injected anomalies and their ground truth."""

from dataclasses import dataclass
from typing import Any

from simulator.anomalies import INJECTORS, Anomaly, Injector, Target
from simulator.config import Config
from simulator.records import RECORD_TYPES, Record, money
from simulator.sim import Sim

GROUND_TRUTH_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class Dataset:
    records: dict[str, list[Record]]
    ground_truth: dict[str, Any]


def _targets(sim: Sim, injector: Injector) -> list[Target]:
    count = injector.count(sim)
    match injector.target:
        case "order":
            return list(sim.claim_orders(count))
        case "refundable_order":
            return list(sim.claim_orders(count, refundable=True))
        case "settlement":
            return list(sim.claim_settlements(injector.name))
        case "none":
            return [None] * count


def _inject(sim: Sim, phase: str) -> list[Anomaly]:
    return [
        injector.apply(sim, target)
        for injector in INJECTORS
        if injector.phase == phase
        for target in _targets(sim, injector)
    ]


def _expected_links(sim: Sim) -> list[dict[str, str]]:
    """order -> payment -> settlement -> bank credit, for chains no anomaly touches."""
    credit_by_settlement = {b.description.split()[2]: b for b in sim.bank_transactions}
    links = []
    for order in sim.orders:
        if order.order_id in sim.claimed_orders:
            continue
        payment = sim.payment_of(order)
        if payment.settlement_ref in sim.claimed_settlements:
            continue
        links.append(
            {
                "order_id": order.order_id,
                "payment_id": payment.payment_id,
                "settlement_id": payment.settlement_ref,
                "bank_transaction_id": credit_by_settlement[
                    payment.settlement_ref
                ].bank_transaction_id,
            }
        )
    return links


def _anomaly_entry(index: int, anomaly: Anomaly, currency: str) -> dict[str, Any]:
    return {
        "anomaly_id": f"ANM-{index:04d}",
        "type": anomaly.type,
        "subtype": anomaly.subtype,
        "records": [{"source": s, "external_id": e} for s, e in anomaly.records],
        "expected_delta": money(anomaly.expected_delta),
        "currency": currency,
        "description": anomaly.description,
        "injector": anomaly.injector,
        "invariants_broken": list(anomaly.invariants),
    }


def generate(config: Config, seed: int) -> Dataset:
    sim = Sim(config, seed)
    sim.generate_orders_and_payments()
    for injector in INJECTORS:
        if injector.target == "settlement":
            sim.reserve_batches(injector.name, injector.count(sim))
    anomalies = _inject(sim, "records")
    sim.generate_refunds()
    sim.build_settlements()
    sim.build_bank_credits()
    anomalies += _inject(sim, "bank")
    records: dict[str, list[Record]] = {name: list(getattr(sim, name)) for name in RECORD_TYPES}
    ground_truth = {
        "schema_version": GROUND_TRUTH_SCHEMA_VERSION,
        "seed": seed,
        "anomalies": [
            _anomaly_entry(i, a, config.currency) for i, a in enumerate(anomalies, start=1)
        ],
        "expected_links": _expected_links(sim),
    }
    return Dataset(records, ground_truth)
