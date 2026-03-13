"""Typed callback contexts for exchange manager collaboration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from service.exchange_types import ExchangeOrderPayload, ParsedOrderStatus


@dataclass(frozen=True)
class BuyFinalizationContext:
    """Dependencies required to finalize a filled market buy."""

    parse_order_status: Callable[[ExchangeOrderPayload], Awaitable[ParsedOrderStatus]]
    get_precision_for_symbol: Callable[[str], Awaitable[int]]
    resolve_symbol: Callable[[str], str | None]
    get_demo_taker_fee_for_symbol: Callable[[str], float]


@dataclass(frozen=True)
class SellRoutingContext:
    """Dependencies required to route a sell by configured execution mode."""

    create_spot_limit_sell: Callable[
        [ExchangeOrderPayload, dict[str, Any]],
        Awaitable[dict[str, Any] | None],
    ]
    create_spot_market_sell: Callable[
        [ExchangeOrderPayload, dict[str, Any]],
        Awaitable[dict[str, Any] | None],
    ]
    can_fallback_to_market_sell: Callable[
        [ExchangeOrderPayload, dict[str, Any]],
        Awaitable[bool],
    ]


@dataclass(frozen=True)
class MarketSellExecutionContext:
    """Dependencies required to execute and finalize a market sell."""

    ensure_exchange: Callable[[dict[str, Any]], Awaitable[None]]
    ensure_markets_loaded: Callable[[], Awaitable[None]]
    resolve_symbol: Callable[[str], str | None]
    resolve_sell_amount: Callable[
        [str, float],
        Awaitable[tuple[str, float] | None],
    ]
    reduce_amount_by_step: Callable[[str, float, int], float]
    is_notional_below_minimum: Callable[
        [str, float, float],
        tuple[bool, float | None, float],
    ]
    get_price_for_symbol: Callable[[str], Awaitable[str]]
    log_remaining_sell_dust: Callable[[str], Awaitable[None]]
    build_sell_order_status: Callable[
        [ExchangeOrderPayload],
        Awaitable[dict[str, Any] | None],
    ]


@dataclass(frozen=True)
class LimitSellPlacementContext:
    """Dependencies required to place and hand off a limit sell."""

    ensure_exchange: Callable[[dict[str, Any]], Awaitable[None]]
    ensure_markets_loaded: Callable[[], Awaitable[None]]
    resolve_symbol: Callable[[str], str | None]
    resolve_sell_amount: Callable[
        [str, float],
        Awaitable[tuple[str, float] | None],
    ]
    is_notional_below_minimum: Callable[
        [str, float, float],
        tuple[bool, float | None, float],
    ]
    get_price_for_symbol: Callable[[str], Awaitable[str]]
    handle_limit_sell_fill: Callable[
        [ExchangeOrderPayload, str, dict[str, Any], ExchangeOrderPayload],
        Awaitable[dict[str, Any] | None],
    ]


@dataclass(frozen=True)
class LimitSellFillContext:
    """Dependencies required to reconcile a placed limit sell."""

    parse_order_status: Callable[[ExchangeOrderPayload], Awaitable[ParsedOrderStatus]]
    build_sell_order_status: Callable[
        [ExchangeOrderPayload],
        Awaitable[dict[str, Any] | None],
    ]
