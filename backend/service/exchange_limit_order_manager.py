"""Shared limit-sale price resolution and CCXT submission."""

from typing import Any

import ccxt.async_support as ccxt
from service.exchange_capabilities import (
    ExchangePostSubmissionFailure,
    ExchangeSubmissionIndeterminate,
    build_client_order_params,
)
from service.exchange_types import ExchangeOrderPayload


class ExchangeLimitOrderManager:
    """Resolve exchange prices and submit limit sales without close accounting."""

    def __init__(self, logger: Any, get_exchange: Any):
        self._logger = logger
        self._get_exchange = get_exchange

    async def resolve_limit_sell_price(
        self,
        *,
        order: ExchangeOrderPayload,
        resolved_symbol: str,
        get_price_for_symbol: Any,
    ) -> str:
        """Resolve the limit price from payload or live ticker."""
        exchange = self._get_exchange()
        explicit_limit_price = order.get("limit_price")
        current_price = order.get("current_price")
        if exchange is None:
            raise ValueError("Exchange client is not available")
        if explicit_limit_price and float(explicit_limit_price) > 0:
            return exchange.price_to_precision(
                resolved_symbol,
                float(explicit_limit_price),
            )
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
            trade = await exchange.create_order(
                resolved_symbol,
                "limit",
                "sell",
                amount,
                limit_price,
                build_client_order_params(order.get("client_order_id")),
            )
            if not isinstance(trade, dict) or not trade.get("id"):
                evidence = dict(order)
                if isinstance(trade, dict):
                    evidence.update(trade)
                evidence["symbol"] = resolved_symbol
                raise ExchangePostSubmissionFailure(
                    action="limit_sell",
                    symbol=resolved_symbol,
                    order=evidence,
                    cause=TypeError(
                        "Exchange accepted the limit sell but returned no order id"
                    ),
                    operation_id=str(order.get("operation_id") or "") or None,
                )
            return trade
        except ccxt.ExchangeError as exc:
            self._logger.error(
                "Limit sell for %s failed due to an exchange error: %s",
                order["symbol"],
                exc,
            )
            return None
        except ccxt.NetworkError as exc:
            raise ExchangeSubmissionIndeterminate(
                action="limit_sell",
                symbol=str(order["symbol"]),
                client_order_id=str(order.get("client_order_id") or "") or None,
            ) from exc
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
