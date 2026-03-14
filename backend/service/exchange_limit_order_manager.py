"""Limit sell order placement helpers."""

from typing import Any

import ccxt.async_support as ccxt
from service.exchange_contexts import LimitSellPlacementContext
from service.exchange_limit_sell import build_market_fallback_status
from service.exchange_types import ExchangeOrderPayload


class ExchangeLimitOrderManager:
    """Own limit-sell placement and pre-fill validation."""

    def __init__(self, logger: Any, get_exchange: Any):
        self._logger = logger
        self._get_exchange = get_exchange

    async def create_spot_limit_sell(
        self,
        *,
        order: ExchangeOrderPayload,
        config: dict[str, Any],
        context: LimitSellPlacementContext,
    ) -> dict[str, Any] | None:
        """Create a spot limit sell order and wait for fill handling."""
        exchange = self._get_exchange()
        if exchange is None:
            return None

        await context.ensure_exchange(config)
        await context.ensure_markets_loaded()

        resolved_symbol = await context.resolve_symbol(order["symbol"])
        if resolved_symbol is None:
            self._logger.error(
                "Cannot place limit sell. Symbol not found: %s",
                order["symbol"],
            )
            return None

        sell_amount = await context.resolve_sell_amount(
            resolved_symbol,
            float(order["total_amount"]),
        )
        if sell_amount is None:
            self._logger.error(
                "Skipping limit sell for %s: no available amount to sell.",
                resolved_symbol,
            )
            return None

        resolved_symbol, amount_value = sell_amount
        amount = exchange.amount_to_precision(resolved_symbol, amount_value)
        limit_price = await self.resolve_limit_sell_price(
            order=order,
            resolved_symbol=resolved_symbol,
            get_price_for_symbol=context.get_price_for_symbol,
        )
        limit_price_value = float(limit_price)

        below_min_notional, min_notional, estimated_notional = (
            context.is_notional_below_minimum(
                resolved_symbol,
                amount_value,
                limit_price_value,
            )
        )
        if below_min_notional:
            self._logger.info(
                "Skipping limit sell for %s: estimated notional %.8f is below "
                "minimum %.8f. Trying market fallback if enabled.",
                resolved_symbol,
                estimated_notional,
                float(min_notional or 0.0),
            )
            return build_market_fallback_status(
                symbol=resolved_symbol,
                remaining_amount=float(amount_value),
                fallback_reason="minimum_notional",
            )

        self._logger.info(
            "Placing limit sell for %s amount=%s price=%s",
            resolved_symbol,
            amount,
            limit_price,
        )
        trade = await self.execute_limit_sell(
            resolved_symbol=resolved_symbol,
            amount=amount,
            limit_price=limit_price,
            order=order,
        )
        if not trade:
            return build_market_fallback_status(
                symbol=resolved_symbol,
                remaining_amount=float(amount_value),
                fallback_reason="limit_order_placement_failed",
            )

        sell_order = dict(order)
        sell_order.update(trade)
        sell_order["symbol"] = resolved_symbol
        sell_order["total_amount"] = float(amount_value)
        if not sell_order.get("id"):
            self._logger.error(
                "Limit sell for %s returned no order id.",
                resolved_symbol,
            )
            return build_market_fallback_status(
                symbol=resolved_symbol,
                remaining_amount=float(amount_value),
                fallback_reason="limit_order_missing_id",
            )

        return await context.handle_limit_sell_fill(
            sell_order,
            resolved_symbol,
            config,
            order,
        )

    async def resolve_limit_sell_price(
        self,
        *,
        order: ExchangeOrderPayload,
        resolved_symbol: str,
        get_price_for_symbol: Any,
    ) -> str:
        """Resolve the limit price from payload or live ticker."""
        exchange = self._get_exchange()
        current_price = order.get("current_price")
        if exchange is None:
            raise ValueError("Exchange client is not available")
        if current_price and float(current_price) > 0:
            return exchange.price_to_precision(resolved_symbol, float(current_price))

        self._logger.debug(
            "Limit sell for %s has no current_price payload. "
            "Fetching live ticker price.",
            resolved_symbol,
        )
        live_price = await get_price_for_symbol(resolved_symbol)
        return exchange.price_to_precision(resolved_symbol, float(live_price))

    async def execute_limit_sell(
        self,
        *,
        resolved_symbol: str,
        amount: str,
        limit_price: str,
        order: ExchangeOrderPayload,
    ) -> dict[str, Any] | None:
        """Place a limit sell order through the current exchange client."""
        exchange = self._get_exchange()
        if exchange is None:
            return None

        try:
            return await exchange.create_order(
                resolved_symbol,
                "limit",
                "sell",
                amount,
                limit_price,
                {},
            )
        except ccxt.ExchangeError as exc:
            self._logger.error(
                "Limit sell for %s failed due to an exchange error: %s",
                order["symbol"],
                exc,
            )
            return None
        except ccxt.NetworkError as exc:
            self._logger.error(
                "Limit sell for %s failed due to a network error: %s",
                order["symbol"],
                exc,
            )
            return None
        except ccxt.BaseError as exc:
            self._logger.error(
                "Limit sell for %s failed due to an error: %s",
                order["symbol"],
                exc,
            )
            return None
        except (TypeError, ValueError, RuntimeError, KeyError) as exc:
            self._logger.error(
                "Limit sell for %s failed with: %s",
                order["symbol"],
                exc,
            )
            return None
