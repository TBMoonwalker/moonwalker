"""Sell execution orchestration helpers."""

from typing import Any

import ccxt.async_support as ccxt
from service.exchange_contexts import MarketSellExecutionContext, SellRoutingContext
from service.exchange_helpers import safe_float
from service.exchange_limit_sell import build_partial_status_from_fallback
from service.exchange_sell_status import (
    build_partial_sell_status,
    combine_partial_sell_statuses,
    merge_partial_fill_with_market_sell,
)
from service.exchange_types import ExchangeOrderPayload
from tenacity import TryAgain


class ExchangeSellManager:
    """Own sell execution orchestration for market and limit fallback paths."""

    def __init__(self, logger: Any, get_exchange: Any):
        self._logger = logger
        self._get_exchange = get_exchange

    async def create_spot_sell(
        self,
        *,
        order: ExchangeOrderPayload,
        config: dict[str, Any],
        context: SellRoutingContext,
    ) -> dict[str, Any] | None:
        """Create a sell order using configured execution mode."""
        sell_order_type = str(config.get("sell_order_type", "market")).lower()
        if sell_order_type != "limit":
            return await context.create_spot_market_sell(order, config)

        order_status = await context.create_spot_limit_sell(order, config)
        if order_status:
            fallback_reason = str(order_status.get("fallback_reason") or "")
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

            if not await context.can_fallback_to_market_sell(order, config):
                return build_partial_status_from_fallback(
                    order_status,
                    default_symbol=str(order.get("symbol")),
                )

            self._log_market_fallback_reason(order, fallback_reason)
            remaining_order = dict(order)
            remaining_order["total_amount"] = float(
                order_status.get("remaining_amount") or 0.0
            )
            market_status = await context.create_spot_market_sell(
                remaining_order, config
            )
            if not market_status:
                self._logger.warning(
                    "Market fallback for %s did not create an exchange order. "
                    "fallback_reason=%s remaining_amount=%s",
                    order.get("symbol"),
                    fallback_reason or "unknown",
                    remaining_order.get("total_amount"),
                )
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

        self._logger.info(
            "Limit sell for %s failed before exchange confirmation. "
            "No fallback status was returned.",
            order.get("symbol"),
        )
        return None

    def _log_market_fallback_reason(
        self,
        order: ExchangeOrderPayload,
        fallback_reason: str,
    ) -> None:
        """Log why a limit sell is being converted into a market sell."""
        symbol = order.get("symbol")
        if fallback_reason == "limit_order_placement_failed":
            self._logger.warning(
                "Limit sell for %s could not be placed on the exchange. "
                "Falling back to market sell.",
                symbol,
            )
            return
        if fallback_reason == "limit_order_missing_id":
            self._logger.warning(
                "Limit sell for %s returned no exchange order id. "
                "Falling back to market sell.",
                symbol,
            )
            return
        if fallback_reason == "limit_order_partial_timeout":
            self._logger.info(
                "Limit sell for %s partially filled and timed out. "
                "Falling back to market sell for the remainder.",
                symbol,
            )
            return
        if fallback_reason == "minimum_notional":
            self._logger.info(
                "Limit sell for %s was below minimum notional. "
                "Trying market fallback if possible.",
                symbol,
            )
            return
        self._logger.info(
            "Limit sell for %s was not filled. Falling back to market sell.",
            symbol,
        )

    async def create_spot_market_sell(
        self,
        *,
        order: ExchangeOrderPayload,
        config: dict[str, Any],
        context: MarketSellExecutionContext,
    ) -> dict[str, Any] | None:
        """Create a spot market sell order."""
        await context.ensure_exchange(config)
        await context.ensure_markets_loaded()
        exchange = self._get_exchange()
        if exchange is None:
            self._logger.error(
                "Skipping market sell for %s: exchange client is unavailable.",
                order.get("symbol"),
            )
            return None
        resolved_symbol = await context.resolve_symbol(order["symbol"])
        if resolved_symbol is None:
            self._logger.error(
                "Selling pair %s failed: symbol not found.", order["symbol"]
            )
            return None

        try:
            requested_amount = float(order["total_amount"])
            sell_amount = await context.resolve_sell_amount(
                resolved_symbol,
                requested_amount,
            )
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
                reduced_amount = context.reduce_amount_by_step(
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
                        await context.get_price_for_symbol(resolved_symbol)
                    )
                except (ccxt.BaseError, RuntimeError, TypeError, ValueError):
                    notional_price_value = None

            fallback_min_price = safe_float(order.get("fallback_min_price"))
            if fallback_min_price and fallback_min_price > 0:
                if notional_price_value is None or notional_price_value <= 0:
                    self._logger.warning(
                        "Skipping market sell for %s: could not verify current "
                        "price against minimum sell price %.10f. Keeping "
                        "position open for a later retry.",
                        resolved_symbol,
                        fallback_min_price,
                    )
                    return build_partial_sell_status(
                        symbol=resolved_symbol,
                        partial_amount=0.0,
                        partial_avg_price=0.0,
                        remaining_amount=float(order["total_amount"]),
                    )
                if notional_price_value < fallback_min_price:
                    self._logger.info(
                        "Skipping market sell for %s: current price %.10f is "
                        "below minimum sell price %.10f. Keeping position open "
                        "for a later retry.",
                        resolved_symbol,
                        notional_price_value,
                        fallback_min_price,
                    )
                    return build_partial_sell_status(
                        symbol=resolved_symbol,
                        partial_amount=0.0,
                        partial_avg_price=0.0,
                        remaining_amount=float(order["total_amount"]),
                    )

            if notional_price_value and notional_price_value > 0:
                below_min_notional, min_notional, estimated_notional = (
                    context.is_notional_below_minimum(
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
            await context.log_remaining_sell_dust(resolved_symbol)
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
            return await context.build_sell_order_status(order)

        return None
