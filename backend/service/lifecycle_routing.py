"""Resolve lifecycle ownership before legacy aggregation or order admission."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

import model
from service.order_requests import normalize_order_symbol
from service.spot_campaign_types import TradeLifecycleMode, parse_lifecycle_mode
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Q
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


async def has_pending_accumulation_work(
    *,
    activation_id: UUID | None = None,
    connection: BaseDBAsyncClient | None = None,
) -> bool:
    """Keep queued commands and unresolved opportunities with their owner.

    The mode-change boundary also checks all placement intents. During symbol
    routing only linked accumulation placements count: a new DCA intent must
    not be mistaken for old accumulation work during reconciliation.
    """
    commands = model.AccumulationLifecycleOperation.filter(status="pending")
    opportunities = model.AccumulationOpportunity.filter(unresolved_slot__isnull=False)
    if activation_id is not None:
        commands = commands.filter(activation_id=activation_id)
        opportunities = opportunities.filter(activation_id=activation_id)
    if (
        await commands.using_db(connection).exists()
        or await opportunities.using_db(connection).exists()
    ):
        return True
    if activation_id is None:
        return False  # The mode-change boundary already checks every placement.
    return (
        await model.PlacementIntent.filter(
            Q(accumulation_attempt__opportunity__activation_id=activation_id)
            | Q(accumulation_lifecycle_operation__activation_id=activation_id)
        )
        .exclude(state__in=("completed", "rejected"))
        .using_db(connection)
        .exists()
    )


async def load_lifecycle_route(
    symbol: str, *, connection: BaseDBAsyncClient | None = None
) -> LifecycleRoutingDecision:
    """Read both ownership records coherently, propagating database failures.

    A stopped, empty, settled activation releases ownership only after an
    explicitly persisted switch to Dynamic DCA. Its history remains intact.
    Unknown modes and inconsistent ownership never default to DCA.
    Mutation callers must additionally hold the symbol lifecycle lock.
    Supply the caller's transaction when admission and persistence are atomic.
    """
    symbol = normalize_order_symbol(symbol)
    transaction = in_transaction() if connection is None else nullcontext(connection)
    async with transaction as connection:
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
            .values("id", "holding_id", "state")
        )
        released = False
        if (
            activation is not None
            and activation["state"] == "stopped"
            and activation["holding_id"] is None
            and (holding is None or holding["lifecycle_mode"] in (None, "classic_dca"))
        ):
            # Read the committed mode in the same snapshot as ownership. A
            # missing row or a stale caller payload cannot authorize a handoff.
            selected_mode = (
                await model.AppConfig.filter(key="trade_mode", value_type="str")
                .using_db(connection)
                .first()
                .values("value")
            )
            released = (
                selected_mode is not None
                and selected_mode["value"] == "dynamic_dca"
                and not await has_pending_accumulation_work(
                    activation_id=activation["id"], connection=connection
                )
            )
    try:
        mode = parse_lifecycle_mode(holding["lifecycle_mode"] if holding else None)
    except ValueError:
        return LifecycleRoutingDecision(
            LifecycleRoute.BLOCKED, "unknown_lifecycle_mode"
        )
    if released:
        return LifecycleRoutingDecision(
            LifecycleRoute.CLASSIC_DCA, "settled_accumulation_handoff"
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
