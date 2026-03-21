"""Pure helpers for manual dashboard order intents."""

from __future__ import annotations

from typing import Any, TypedDict


class ManualSellOrderIntent(TypedDict):
    """Payload for a manual sell order request."""

    symbol: str
    direction: str
    side: str
    type_sell: str
    actual_pnl: float
    total_cost: float
    current_price: float


class ManualBuyOrderIntent(TypedDict):
    """Payload for a manual buy order request."""

    ordersize: float
    symbol: str
    direction: str
    botname: str
    baseorder: bool
    safetyorder: bool
    order_count: int
    ordertype: str
    so_percentage: float
    side: str


def build_manual_sell_order_intent(
    trades: dict[str, Any], actual_pnl: float
) -> ManualSellOrderIntent:
    """Build the sell order payload from aggregated trade data."""
    return {
        "symbol": str(trades["symbol"]),
        "direction": str(trades["direction"]),
        "side": "sell",
        "type_sell": "order_sell",
        "actual_pnl": float(actual_pnl),
        "total_cost": float(trades["total_cost"]),
        "current_price": float(trades["current_price"]),
    }


def build_manual_buy_order_intent(
    symbol: str,
    ordersize: float,
    trades: dict[str, Any],
    actual_pnl: float,
) -> ManualBuyOrderIntent:
    """Build the buy order payload from aggregated trade data."""
    safety_order_count = len(trades.get("safetyorders") or [])
    return {
        "ordersize": float(ordersize),
        "symbol": symbol,
        "direction": str(trades["direction"]),
        "botname": str(trades["bot"]),
        "baseorder": False,
        "safetyorder": True,
        "order_count": safety_order_count + 1,
        "ordertype": "market",
        "so_percentage": float(actual_pnl),
        "side": "buy",
    }
