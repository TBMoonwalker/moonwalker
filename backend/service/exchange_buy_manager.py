"""Market buy execution and finalization helpers."""

from typing import Any

import ccxt.async_support as ccxt
from service.exchange_contexts import BuyFinalizationContext
from service.exchange_types import ExchangeOrderPayload, ParsedOrderStatus


class ExchangeBuyManager:
    """Own market buy placement and filled-order normalization."""

    def __init__(self, logger: Any, get_exchange: Any):
        self._logger = logger
        self._get_exchange = get_exchange

    async def execute_market_buy(
        self, order: ExchangeOrderPayload
    ) -> ExchangeOrderPayload | None:
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
        order: ExchangeOrderPayload,
        config: dict[str, Any],
        context: BuyFinalizationContext,
    ) -> ExchangeOrderPayload | None:
        """Enrich a filled buy with normalized trade metadata."""
        exchange = self._get_exchange()
        if exchange is None:
            return None

        self._logger.info("Opened trade: %s", order)

        order_status: ParsedOrderStatus = await context.parse_order_status(order)
        if "timestamp" in order_status:
            order["timestamp"] = order_status["timestamp"]
        if "amount" in order_status:
            order["amount"] = order_status["amount"]
        if "total_amount" in order_status:
            order["total_amount"] = order_status["total_amount"]
        elif "amount" in order_status:
            order["total_amount"] = float(order_status["amount"])
        if "price" in order_status:
            order["price"] = order_status["price"]
        if "orderid" in order_status:
            order["orderid"] = order_status["orderid"]
        if "symbol" in order_status:
            order["symbol"] = order_status["symbol"]
        if "side" in order_status:
            order["side"] = order_status["side"]
        if "amount_fee" in order_status:
            order["amount_fee"] = order_status["amount_fee"]
        if "base_fee" in order_status:
            order["base_fee"] = order_status["base_fee"]
        if "ordersize" in order_status:
            order["ordersize"] = order_status["ordersize"]
        if not order.get("amount") or float(order["amount"]) <= 0:
            self._logger.error(
                "Buy order for %s returned zero amount. Skipping trade creation.",
                order.get("symbol"),
            )
            return None

        status_symbol = str(order_status.get("symbol") or order.get("symbol") or "")
        if not status_symbol:
            self._logger.error(
                "Cannot finalize buy: symbol is missing from order data."
            )
            return None

        order["precision"] = await context.get_precision_for_symbol(status_symbol)
        resolved_symbol = await context.resolve_symbol(status_symbol)
        if resolved_symbol is None:
            self._logger.error(
                "Cannot finalize buy for %s: symbol not found.",
                status_symbol,
            )
            return None

        order["amount"] = float(order_status.get("amount") or order["amount"])
        order["amount_fee"] = 0.0
        order["fees"] = 0.0

        if config.get("dry_run", True):
            try:
                order["fees"] = context.get_demo_taker_fee_for_symbol(status_symbol)
            except (ValueError, TypeError, ccxt.BaseError) as exc:
                self._logger.warning(
                    "Demo mode fee lookup for %s failed (%s). "
                    "Using taker fee 0.0 as fallback.",
                    status_symbol,
                    exc,
                )
                order["fees"] = 0.0
        else:
            try:
                fees = await exchange.fetch_trading_fee(symbol=status_symbol)
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
            net_amount = max(0.0, float(order["amount"]) - order["amount_fee"])
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
