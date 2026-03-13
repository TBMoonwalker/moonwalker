"""Market buy execution and finalization helpers."""

from collections.abc import Awaitable, Callable
from typing import Any

import ccxt.async_support as ccxt


class ExchangeBuyManager:
    """Own market buy placement and filled-order normalization."""

    def __init__(self, logger: Any, get_exchange: Callable[[], Any]):
        self._logger = logger
        self._get_exchange = get_exchange

    async def execute_market_buy(self, order: dict[str, Any]) -> dict[str, Any] | None:
        """Place a market buy order through the current exchange client."""
        exchange = self._get_exchange()
        if exchange is None:
            return None

        try:
            self._logger.info("Try to buy %s %s", order["amount"], order["symbol"])
            trade = await exchange.create_order(
                order["symbol"],
                order["ordertype"],
                order["side"],
                order["amount"],
                order["price"],
                {},
            )
            order.update(trade)
            return order
        except ccxt.ExchangeError as exc:
            self._logger.error(
                "Buying pair %s failed due to an exchange error: %s",
                order["symbol"],
                exc,
            )
            return None
        except ccxt.NetworkError as exc:
            self._logger.error(
                "Buying pair %s failed due to an network error: %s",
                order["symbol"],
                exc,
            )
            return None
        except ccxt.BaseError as exc:
            self._logger.error(
                "Buying pair %s failed due to an error: %s", order["symbol"], exc
            )
            return None
        except (TypeError, ValueError, RuntimeError, KeyError) as exc:
            self._logger.error("Buying pair %s failed with: %s", order["symbol"], exc)
            return None

    async def finalize_market_buy(
        self,
        *,
        order: dict[str, Any],
        config: dict[str, Any],
        parse_order_status: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        get_precision_for_symbol: Callable[[str], Awaitable[int]],
        resolve_symbol: Callable[[str], str | None],
        get_demo_taker_fee_for_symbol: Callable[[str], float],
    ) -> dict[str, Any] | None:
        """Enrich a filled buy with normalized trade metadata."""
        exchange = self._get_exchange()
        if exchange is None:
            return None

        self._logger.info("Opened trade: %s", order)

        order_status = await parse_order_status(order)
        order.update(order_status)
        if not order.get("amount") or float(order["amount"]) <= 0:
            self._logger.error(
                "Buy order for %s returned zero amount. Skipping trade creation.",
                order.get("symbol"),
            )
            return None

        order["precision"] = await get_precision_for_symbol(order_status["symbol"])
        resolved_symbol = resolve_symbol(order_status["symbol"])
        if resolved_symbol is None:
            self._logger.error(
                "Cannot finalize buy for %s: symbol not found.",
                order_status["symbol"],
            )
            return None

        order["amount"] = float(order_status["amount"])
        order["amount_fee"] = 0.0
        order["fees"] = 0.0

        if config.get("dry_run", True):
            try:
                order["fees"] = get_demo_taker_fee_for_symbol(order_status["symbol"])
            except (ValueError, TypeError, ccxt.BaseError) as exc:
                self._logger.warning(
                    "Demo mode fee lookup for %s failed (%s). "
                    "Using taker fee 0.0 as fallback.",
                    order_status["symbol"],
                    exc,
                )
                order["fees"] = 0.0
        else:
            try:
                fees = await exchange.fetch_trading_fee(symbol=order_status["symbol"])
                order["fees"] = float(fees.get("taker", 0.0))
            except (ccxt.BaseError, TypeError, ValueError) as exc:
                self._logger.warning(
                    "Fetching fee rate for pair %s failed (%s). Using 0.0 fallback.",
                    order["symbol"],
                    exc,
                )
                order["fees"] = 0.0

        if not config.get("fee_deduction", False):
            order["amount_fee"] = float(order_status.get("base_fee") or 0.0)
            net_amount = max(0.0, float(order_status["amount"]) - order["amount_fee"])
            order["amount"] = float(net_amount)

            self._logger.debug(
                "Fee Deduction not active. Real amount %s, deducted amount %s, "
                "base fee %s",
                order_status["amount"],
                order["amount"],
                order["amount_fee"],
            )

        self._logger.debug(order)
        return order
