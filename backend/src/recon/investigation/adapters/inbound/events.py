"""Inbound event handlers: Reconciliation's events translated into Investigation commands
(anti-corruption layer, bounded-contexts.md)."""

import uuid
from collections.abc import Callable

from recon.investigation.application.open_case import OpenCase


def on_discrepancy_detected(open_case: OpenCase) -> Callable[[dict[str, object]], None]:
    """``DiscrepancyDetected`` opens its discrepancy's case; a redelivery finds it open."""

    def handle(payload: dict[str, object]) -> None:
        open_case(uuid.UUID(str(payload["discrepancy_id"])))

    return handle
