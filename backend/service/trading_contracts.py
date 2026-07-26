"""Required service-boundary contracts for trading intents and fills."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class BuyIntent(TypedDict):
    """Normalized buy request accepted by order orchestration."""

    ordersize: float
    symbol: str
    direction: str
    botname: str
    baseorder: bool
    safetyorder: bool
    order_count: int
    ordertype: str
    so_percentage: float | None
    side: str
    signal_name: NotRequired[str | None]
    strategy_name: NotRequired[str | None]
    timeframe: NotRequired[str | None]
    metadata_json: NotRequired[str | None]
    baseline_order_size: NotRequired[float]
    entry_size_applied: NotRequired[bool]
    entry_size_reason_code: NotRequired[str | None]
    entry_size_fallback_applied: NotRequired[bool]
    entry_size_fallback_reason: NotRequired[str | None]
    campaign_id: NotRequired[str | None]
    _ai_entry_evaluation: NotRequired[Any]


class SellIntent(TypedDict):
    """Normalized sell request accepted by order orchestration."""

    symbol: str
    direction: str
    side: str
    type_sell: str
    actual_pnl: float
    total_cost: float
    current_price: float
    sell_reason: str
    campaign_id: NotRequired[str | None]
    skip_tp_limit_cancel: NotRequired[bool]
    total_amount: NotRequired[float]
    requested_total_amount: NotRequired[float]
