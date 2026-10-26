"""Recover application identities and distinguish declared CSV fee uncertainty."""

import json
import re
from typing import Any

import model
from service.accumulation.commands import ENTRY_ACTIONS
from service.accumulation.imports import AccumulationImport
from service.exchange_capabilities import build_client_order_id


def recoverable_client_order_id(placement: Any) -> str | None:
    """Return stored evidence or the original deterministic native UUID identity."""
    if placement.client_order_id:
        return str(placement.client_order_id)
    try:
        evidence = json.loads(placement.result_json or "null")
        if (
            isinstance(evidence, dict)
            and evidence.get("symbol") == placement.symbol
            and evidence.get("side") == placement.side
            and (
                not placement.exchange_order_id
                or evidence.get("id") == placement.exchange_order_id
            )
        ):
            client_id = evidence.get("clientOrderId")
            if isinstance(client_id, str) and 0 < len(client_id) <= 128:
                return client_id
    except (ValueError, TypeError):
        pass
    if re.fullmatch(r"(?:buy|sell)-[0-9a-f]{32}", placement.operation_id):
        return build_client_order_id(placement.operation_id)
    return None


async def declared_unknown_fee_count(activation: Any, connection: Any) -> int:
    """Only a validated CSV declaration can explain permanent historical fee gaps."""
    entry = (
        await model.AccumulationLifecycleOperation.filter(
            activation=activation, action__in=ENTRY_ACTIONS, status="applied"
        )
        .using_db(connection)
        .order_by("id")
        .first()
    )
    if entry is None:
        return 0
    try:
        body = json.loads(entry.request_json)
        if not isinstance(body, dict) or body.get("source") != "csv":
            return 0
        return len(AccumulationImport.from_dict(body["imported_inventory"]).entries)
    except (ValueError, TypeError, KeyError):
        return 0


def native_client_identity(placement: Any) -> str | None:
    """Require the native UUID namespace before using an ID as account proof."""
    if not re.fullmatch(r"(?:buy|sell)-[0-9a-f]{32}", placement.operation_id):
        return None
    expected = build_client_order_id(placement.operation_id)
    return expected if recoverable_client_order_id(placement) == expected else None


def recorded_exchange_order_id(checkpoint: Any) -> str | None:
    """Recover an audit lookup address, without treating it as account proof."""
    if checkpoint.placement.exchange_order_id:
        return str(checkpoint.placement.exchange_order_id)
    try:
        evidence = json.loads(checkpoint.evidence_json)
        value = evidence.get("order_id")
        if (
            evidence.get("symbol") == checkpoint.placement.symbol
            and evidence.get("side") == checkpoint.placement.side
            and isinstance(value, str)
            and 0 < len(value) <= 128
        ):
            return value
    except (ValueError, TypeError, AttributeError):
        pass
    return None


async def retire_superseded_ownership_checks(
    activation: Any, current: Any, connection: Any
) -> None:
    """Successful proof supersedes only older read-only ownership/lookup receipts."""
    await (
        model.AccumulationLifecycleOperation.filter(
            activation=activation,
            status="quarantined",
            action__in={"repair_order", "rebind_account", "declare_ownership"},
            result_revision__lt=activation.revision,
        )
        .exclude(id=current.id)
        .using_db(connection)
        .update(
            status="cancelled",
            reason="superseded_by_verified_repair",
            result_state=activation.state,
            result_revision=activation.revision,
        )
    )
