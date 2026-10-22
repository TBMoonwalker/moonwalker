"""Resolve lifecycle ownership before legacy aggregation or order admission."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import model
from service.order_requests import normalize_order_symbol
from service.spot_campaign_types import TradeLifecycleMode, parse_lifecycle_mode
from tortoise.transactions import in_transaction


class LifecycleRoute(StrEnum):
    """Mutually exclusive destinations for persisted lifecycle ownership."""

    CLASSIC_DCA = "classic_dca"
    ACCUMULATION = "accumulation"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class LifecycleRoutingDecision:
    """Compact authoritative route; no lifetime execution history is loaded."""

    route: LifecycleRoute
    reason: str


async def load_lifecycle_route(symbol: str) -> LifecycleRoutingDecision:
    """Read both ownership records coherently, propagating database failures.

    An activation owns its symbol even without an OpenTrades row and even while
    stopped. Unknown modes and inconsistent ownership never default to DCA.
    Mutation callers must additionally hold the symbol lifecycle lock.
    """
    symbol = normalize_order_symbol(symbol)
    async with in_transaction() as connection:
        holding = (
            await model.OpenTrades.filter(symbol=symbol)
            .using_db(connection)
            .first()
            .values("id", "lifecycle_mode")
        )
        activation = (
            await model.AccumulationActivation.filter(symbol=symbol)
            .using_db(connection)
            .first()
            .values("holding_id")
        )
    try:
        mode = parse_lifecycle_mode(holding["lifecycle_mode"] if holding else None)
    except ValueError:
        return LifecycleRoutingDecision(
            LifecycleRoute.BLOCKED, "unknown_lifecycle_mode"
        )
    if activation is not None:
        if holding is not None and (
            mode != TradeLifecycleMode.ACCUMULATION
            or activation["holding_id"] != holding["id"]
        ):
            return LifecycleRoutingDecision(
                LifecycleRoute.BLOCKED, "lifecycle_conflict"
            )
        if holding is None and activation["holding_id"] is not None:
            return LifecycleRoutingDecision(
                LifecycleRoute.BLOCKED, "lifecycle_conflict"
            )
        return LifecycleRoutingDecision(
            LifecycleRoute.ACCUMULATION, "accumulation_owned"
        )
    if mode == TradeLifecycleMode.ACCUMULATION:
        return LifecycleRoutingDecision(
            LifecycleRoute.BLOCKED, "accumulation_activation_missing"
        )
    return LifecycleRoutingDecision(LifecycleRoute.CLASSIC_DCA, "classic_dca")
