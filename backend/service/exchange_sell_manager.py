"""Sell execution orchestration helpers."""

from collections.abc import Awaitable, Callable
from typing import Any

import ccxt.async_support as ccxt
from service.exchange_helpers import safe_float
from service.exchange_limit_sell import build_partial_status_from_fallback
from service.exchange_sell_status import (
    build_partial_sell_status,
    combine_partial_sell_statuses,
    merge_partial_fill_with_market_sell,
)
from tenacity import TryAgain


class ExchangeSellManager:
    """Own sell execution orchestration for market and limit fallback paths."""

    def __init__(
        self,
        logger: Any,
        get_exchange: Callable[[], Any],
    ):
        self._logger = logger
        self._get_exchange = get_exchange

    async def create_spot_sell(
        self,
        *,
        order: dict[str, Any],
        config: dict[str, Any],
        create_spot_limit_sell: Callable[
            [dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any] | None]
        ],
        create_spot_market_sell: Callable[
            [dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any] | None]
        ],
        can_fallback_to_market_sell: Callable[
            [dict[str, Any], dict[str, Any]], Awaitable[bool]
        ],
    ) -> dict[str, Any] | None:
        """Create a sell order using configured execution mode."""
        sell_order_type = str(config.get("sell_order_type", "market")).lower()
        if sell_order_type != "limit":
            return await create_spot_market_sell(order, config)

        order_status = await create_spot_limit_sell(order, config)
        if order_status:
            if not order_status.get("requires_market_fallback"):
                return order_status

            if not bool(order_status.get("limit_cancel_confirmed", False)):
                self._logger.error(
                    "Skipping market fallback for %s because limit cancel "
                    "was not confirmed.",
                    order.get("symbol"),
                )
                return None

            if not bool(config.get("limit_sell_fallback_to_market", True)):
                self._logger.info(
                    "Limit sell for %s partially filled, but market fallback is disabled.",
                    order.get("symbol"),
                )
                return build_partial_status_from_fallback(
                    order_status,
                    default_symbol=str(order.get("symbol")),
                )

            if not await can_fallback_to_market_sell(order, config):
                return build_partial_status_from_fallback(
                    order_status,
                    default_symbol=str(order.get("symbol")),
                )

            self._logger.info(
                "Limit sell for %s was not filled. Falling back to market sell.",
                order.get("symbol"),
            )
            remaining_order = dict(order)
            remaining_order["total_amount"] = float(
                order_status.get("remaining_amount") or 0.0
            )
            market_status = await create_spot_market_sell(remaining_order, config)
            if not market_status:
                return None

            partial_amount = float(order_status.get("partial_filled_amount") or 0.0)
            partial_price = float(order_status.get("partial_avg_price") or 0.0)
            if market_status.get("type") == "partial_sell":
                return combine_partial_sell_statuses(
                    symbol=str(order_status.get("symbol", order.get("symbol"))),
                    first_partial_amount=partial_amount,
                    first_partial_price=partial_price,
                    second_status=market_status,
                )
            return merge_partial_fill_with_market_sell(
                market_status,
                partial_amount=partial_amount,
                partial_price=partial_price,
                total_cost=float(order.get("total_cost") or 0.0),
            )

        if bool(config.get("limit_sell_fallback_to_market", True)):
            if order.get("_limit_cancel_confirmed") is False:
                self._logger.error(
                    "Skipping market fallback for %s because limit cancel "
                    "was not confirmed.",
                    order.get("symbol"),
                )
                return None
            if not await can_fallback_to_market_sell(order, config):
                return None
            self._logger.info(
                "Limit sell for %s was not filled. Falling back to market sell.",
                order.get("symbol"),
            )
            return await create_spot_market_sell(order, config)

        self._logger.info(
            "Limit sell for %s was not filled. Market fallback is disabled.",
            order.get("symbol"),
        )
        return None

    async def create_spot_market_sell(
        self,
        *,
        order: dict[str, Any],
        config: dict[str, Any],
        ensure_exchange: Callable[[dict[str, Any]], Awaitable[None]],
        ensure_markets_loaded: Callable[[], Awaitable[None]],
        resolve_symbol: Callable[[str], str | None],
        resolve_sell_amount: Callable[
            [str, float], Awaitable[tuple[str, float] | None]
        ],
        reduce_amount_by_step: Callable[[str, float, int], float],
        is_notional_below_minimum: Callable[
            [str, float, float], tuple[bool, float | None, float]
        ],
        get_price_for_symbol: Callable[[str], Awaitable[str]],
        log_remaining_sell_dust: Callable[[str], Awaitable[None]],
        build_sell_order_status: Callable[
            [dict[str, Any]], Awaitable[dict[str, Any] | None]
        ],
    ) -> dict[str, Any] | None:
        """Create a spot market sell order."""
        exchange = self._get_exchange()
        if exchange is None:
            return None

        await ensure_exchange(config)
        await ensure_markets_loaded()
        resolved_symbol = resolve_symbol(order["symbol"])
        if resolved_symbol is None:
            self._logger.error(
                "Selling pair %s failed: symbol not found.", order["symbol"]
            )
            return None

        try:
            requested_amount = float(order["total_amount"])
            sell_amount = await resolve_sell_amount(resolved_symbol, requested_amount)
            if sell_amount is None:
                self._logger.error(
                    "Skipping market sell for %s: no available amount to sell.",
                    resolved_symbol,
                )
                return None

            resolved_symbol, available_amount = sell_amount
            order["total_amount"] = available_amount
            if available_amount < requested_amount:
                self._logger.info(
                    "Reducing market sell for %s to available balance: requested=%s available=%s",
                    resolved_symbol,
                    requested_amount,
                    available_amount,
                )

            current_amount = float(order["total_amount"])
            retry_count = int(order.get("_sell_retry_count", 0) or 0)
            if retry_count > 0:
                reduced_amount = reduce_amount_by_step(
                    resolved_symbol,
                    current_amount,
                    retry_count,
                )
                order["total_amount"] = reduced_amount
                self._logger.info(
                    "Reducing amount for sell to: %s", order["total_amount"]
                )
            else:
                order["total_amount"] = float(
                    exchange.amount_to_precision(resolved_symbol, current_amount)
                )

            notional_price_value = safe_float(order.get("current_price"))
            if notional_price_value is None or notional_price_value <= 0:
                try:
                    notional_price_value = float(
                        await get_price_for_symbol(resolved_symbol)
                    )
                except (ccxt.BaseError, RuntimeError, TypeError, ValueError):
                    notional_price_value = None

            if notional_price_value and notional_price_value > 0:
                below_min_notional, min_notional, estimated_notional = (
                    is_notional_below_minimum(
                        resolved_symbol,
                        float(order["total_amount"]),
                        notional_price_value,
                    )
                )
                if below_min_notional:
                    self._logger.info(
                        "Skipping market sell for %s: estimated notional %.8f is "
                        "below minimum %.8f (amount=%s, price=%s).",
                        resolved_symbol,
                        estimated_notional,
                        float(min_notional or 0.0),
                        order["total_amount"],
                        notional_price_value,
                    )
                    return build_partial_sell_status(
                        symbol=resolved_symbol,
                        partial_amount=0.0,
                        partial_avg_price=0.0,
                        remaining_amount=float(order["total_amount"]),
                        unsellable=True,
                        unsellable_reason="minimum_notional",
                        unsellable_min_notional=float(min_notional or 0.0),
                        unsellable_estimated_notional=float(estimated_notional),
                    )

            trade = await exchange.create_market_sell_order(
                resolved_symbol,
                order["total_amount"],
            )
            order.update(trade)
            await log_remaining_sell_dust(resolved_symbol)
        except ccxt.ExchangeError as exc:
            if "insufficient balance" in str(exc):
                self._logger.error(
                    "Trying to sell %s of pair %s failed due insufficient balance.",
                    order["total_amount"],
                    order["symbol"],
                )
                order["_sell_retry_count"] = retry_count + 1
                raise TryAgain
            if "filter failure: notional" in str(exc).lower():
                self._logger.info(
                    "Skipping market sell for %s due NOTIONAL filter failure. "
                    "Keeping position open for a later retry.",
                    resolved_symbol,
                )
                return build_partial_sell_status(
                    symbol=resolved_symbol,
                    partial_amount=0.0,
                    partial_avg_price=0.0,
                    remaining_amount=float(order.get("total_amount") or 0.0),
                    unsellable=True,
                    unsellable_reason="minimum_notional",
                )

            self._logger.error(
                "Selling pair %s failed due to an exchange error: %s",
                order["symbol"],
                exc,
            )
            order = None
        except ccxt.NetworkError as exc:
            self._logger.error(
                "Selling pair %s failed due to an network error: %s",
                order["symbol"],
                exc,
            )
            order = None
        except ccxt.BaseError as exc:
            self._logger.error(
                "Selling pair %s failed due to an error: %s",
                order["symbol"],
                exc,
            )
            order = None
        except (TypeError, ValueError, RuntimeError, KeyError) as exc:
            self._logger.error("Selling pair %s failed with: %s", order["symbol"], exc)
            order = None

        if order:
            if order.get("type") == "partial_sell":
                order.pop("_sell_retry_count", None)
                return order

            self._logger.info(
                "Sold %s %s on Exchange.", order["total_amount"], order["symbol"]
            )
            order.pop("_sell_retry_count", None)
            return await build_sell_order_status(order)

        return None
