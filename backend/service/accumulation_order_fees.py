"""Compatibility adapter for shared authenticated spot-order fee hydration."""

from typing import Any

from service.accumulation_contracts import AccumulationStateError
from service.exchange_order_lookup import hydrate_spot_order_fees


async def hydrate_accumulation_order(
    exchange: Any, order: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    """Retain the accumulation exception contract while using shared evidence."""
    try:
        return await hydrate_spot_order_fees(exchange, order, config)
    except ValueError as exc:
        raise AccumulationStateError(str(exc)) from exc
