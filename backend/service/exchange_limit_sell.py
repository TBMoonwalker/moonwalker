"""Helpers for limit-sell timeout and fallback status handling."""

from typing import Any

from service.exchange_sell_status import build_partial_sell_status
from service.exchange_types import MarketFallbackStatus, PartialSellStatus


def get_limit_sell_timeout_seconds(config: dict[str, Any]) -> int:
    """Return a validated limit sell timeout in seconds."""
    try:
        return max(1, int(config.get("limit_sell_timeout_sec", 60)))
    except (TypeError, ValueError):
        return 60


def build_market_fallback_status(
    *,
    symbol: str,
    remaining_amount: float,
    partial_filled_amount: float = 0.0,
    partial_avg_price: float = 0.0,
    executions: list[dict[str, Any]] | None = None,
    limit_cancel_confirmed: bool = True,
    fallback_reason: str = "limit_order_timeout",
) -> MarketFallbackStatus:
    """Build a status payload that signals market fallback handling."""
    return {
        "requires_market_fallback": True,
        "limit_cancel_confirmed": bool(limit_cancel_confirmed),
        "fallback_reason": fallback_reason,
        "symbol": symbol,
        "remaining_amount": float(remaining_amount),
        "partial_filled_amount": float(partial_filled_amount),
        "partial_avg_price": float(partial_avg_price),
        **({"executions": list(executions)} if executions else {}),
    }


def build_partial_status_from_fallback(
    fallback_status: MarketFallbackStatus,
    *,
    default_symbol: str,
) -> PartialSellStatus:
    """Convert a fallback status payload into a partial sell status."""
    return build_partial_sell_status(
        symbol=str(fallback_status.get("symbol", default_symbol)),
        partial_amount=float(fallback_status.get("partial_filled_amount") or 0.0),
        partial_avg_price=float(fallback_status.get("partial_avg_price") or 0.0),
        remaining_amount=float(fallback_status.get("remaining_amount") or 0.0),
        executions=list(fallback_status.get("executions") or []),
    )
