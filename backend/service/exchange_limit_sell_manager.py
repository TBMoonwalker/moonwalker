"""Limit sell polling and fallback orchestration helpers."""

import asyncio
from typing import Any

import ccxt.async_support as ccxt
from service.exchange_contexts import LimitSellFillContext
from service.exchange_limit_sell import (
    build_market_fallback_status,
    get_limit_sell_timeout_seconds,
)
from service.exchange_types import ExchangeOrderPayload


class ExchangeLimitSellManager:
    """Own limit-sell timeout, cancel, and partial-fill reconciliation."""

    def __init__(self, logger: Any, get_exchange: Any):
        self._logger = logger
        self._get_exchange = get_exchange

    @staticmethod
    def _merge_exchange_order_fields(
        order: ExchangeOrderPayload,
        exchange_order: dict[str, Any],
    ) -> None:
        """Merge relevant CCXT order fields into the mutable sell payload."""
        if "id" in exchange_order:
            order["id"] = str(exchange_order["id"])
        if "symbol" in exchange_order:
            order["symbol"] = str(exchange_order["symbol"])
        if "amount" in exchange_order and exchange_order["amount"] is not None:
            order["amount"] = exchange_order["amount"]
        if "price" in exchange_order and exchange_order["price"] is not None:
            order["price"] = exchange_order["price"]
        if "cost" in exchange_order and exchange_order["cost"] is not None:
            order["cost"] = float(exchange_order["cost"])
        if "timestamp" in exchange_order and exchange_order["timestamp"] is not None:
            order["timestamp"] = int(exchange_order["timestamp"])
        if "fee" in exchange_order:
            order["fee"] = exchange_order["fee"]
        if "side" in exchange_order and exchange_order["side"] is not None:
            order["side"] = str(exchange_order["side"])

    async def wait_for_limit_sell_fill(
        self,
        symbol: str,
        order_id: str,
        timeout_seconds: int,
    ) -> dict[str, Any] | None:
        """Poll an order until it is closed or times out."""
        exchange = self._get_exchange()
        if exchange is None:
            return None

        start_time = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start_time) < timeout_seconds:
            try:
                status = await exchange.fetch_order(order_id, symbol)
                order_status = str(status.get("status", "")).lower()
                filled = float(status.get("filled") or 0.0)
                amount = float(status.get("amount") or 0.0)

                if order_status in {"closed", "filled"} or (
                    amount > 0 and filled >= amount
                ):
                    return status

                if order_status in {"canceled", "cancelled", "rejected", "expired"}:
                    return None
            except ccxt.NetworkError as exc:
                self._logger.warning(
                    "Polling limit sell status failed due to network error: %s", exc
                )
            except ccxt.ExchangeError as exc:
                self._logger.warning(
                    "Polling limit sell status failed due to exchange error: %s", exc
                )
            except ccxt.BaseError as exc:
                self._logger.warning("Polling limit sell status failed: %s", exc)
            except (TypeError, ValueError, RuntimeError, KeyError) as exc:
                self._logger.warning("Polling limit sell status failed: %s", exc)

            await asyncio.sleep(1)

        return None

    async def cancel_order_safe(self, symbol: str, order_id: str) -> None:
        """Cancel an order and only log failures."""
        exchange = self._get_exchange()
        if exchange is None:
            return

        try:
            await exchange.cancel_order(order_id, symbol)
        except (ccxt.BaseError, RuntimeError, TypeError, ValueError) as exc:
            self._logger.warning(
                "Cancel order %s for %s failed or order is already closed: %s",
                order_id,
                symbol,
                exc,
            )

    async def cancel_order_and_confirm(self, symbol: str, order_id: str) -> bool:
        """Cancel an order and confirm it is no longer open."""
        exchange = self._get_exchange()
        if exchange is None:
            return False

        await self.cancel_order_safe(symbol, order_id)

        for _ in range(5):
            try:
                latest = await exchange.fetch_order(order_id, symbol)
                order_status = str(latest.get("status", "")).lower()
                if order_status in {"closed", "filled", "canceled", "cancelled"}:
                    return True
            except (ccxt.BaseError, RuntimeError, TypeError, ValueError) as exc:
                self._logger.warning(
                    "Could not verify cancel status for order %s on %s: %s",
                    order_id,
                    symbol,
                    exc,
                )
            await asyncio.sleep(0.5)

        return False

    async def handle_limit_sell_fill(
        self,
        *,
        sell_order: ExchangeOrderPayload,
        resolved_symbol: str,
        config: dict[str, Any],
        original_order: ExchangeOrderPayload,
        context: LimitSellFillContext,
    ) -> dict[str, Any] | None:
        """Handle limit sell completion, timeout, and partial-fill fallback."""
        exchange = self._get_exchange()
        if exchange is None:
            return None

        timeout_seconds = get_limit_sell_timeout_seconds(config)
        filled_order = await self.wait_for_limit_sell_fill(
            resolved_symbol,
            str(sell_order["id"]),
            timeout_seconds,
        )
        if not filled_order:
            latest_order_status = None
            try:
                latest_order_status = await exchange.fetch_order(
                    str(sell_order["id"]),
                    resolved_symbol,
                )
            except (ccxt.BaseError, RuntimeError, TypeError, ValueError):
                latest_order_status = None

            if latest_order_status:
                filled_amount = float(latest_order_status.get("filled") or 0.0)
                remaining_amount = float(latest_order_status.get("remaining") or 0.0)
                if filled_amount > 0:
                    self._logger.info(
                        "Limit sell for %s partially filled before timeout. "
                        "filled=%s remaining=%s",
                        resolved_symbol,
                        filled_amount,
                        remaining_amount,
                    )
                    if remaining_amount <= 0:
                        self._merge_exchange_order_fields(
                            sell_order,
                            latest_order_status,
                        )
                        return await context.build_sell_order_status(sell_order)

                    cancel_confirmed = await self.cancel_order_and_confirm(
                        resolved_symbol,
                        str(sell_order["id"]),
                    )
                    if not cancel_confirmed:
                        self._logger.error(
                            "Limit order %s for %s partially filled but could not be "
                            "confirmed canceled. Skipping market fallback to avoid "
                            "double-selling.",
                            sell_order["id"],
                            resolved_symbol,
                        )
                        return None

                    partial_fill_status = await context.parse_order_status(sell_order)
                    return build_market_fallback_status(
                        symbol=resolved_symbol,
                        remaining_amount=remaining_amount,
                        partial_filled_amount=float(
                            partial_fill_status.get("total_amount") or filled_amount
                        ),
                        partial_avg_price=float(
                            partial_fill_status.get("price")
                            or latest_order_status.get("average")
                            or latest_order_status.get("price")
                            or 0.0
                        ),
                        fallback_reason="limit_order_partial_timeout",
                    )

            self._logger.info(
                "Limit sell for %s was not filled within %s seconds.",
                resolved_symbol,
                timeout_seconds,
            )
            cancel_confirmed = await self.cancel_order_and_confirm(
                resolved_symbol,
                str(sell_order["id"]),
            )
            if not cancel_confirmed:
                self._logger.error(
                    "Limit order %s for %s was not filled but could not be "
                    "confirmed canceled. Skipping market fallback.",
                    sell_order["id"],
                    resolved_symbol,
                )
                original_order["_limit_cancel_confirmed"] = False
            else:
                original_order["_limit_cancel_confirmed"] = True
            return build_market_fallback_status(
                symbol=resolved_symbol,
                remaining_amount=float(sell_order.get("total_amount") or 0.0),
                limit_cancel_confirmed=bool(
                    original_order.get("_limit_cancel_confirmed", True)
                ),
                fallback_reason="limit_order_timeout",
            )

        self._merge_exchange_order_fields(sell_order, filled_order)
        self._logger.info("Limit sell for %s filled.", resolved_symbol)
        return await context.build_sell_order_status(sell_order)
