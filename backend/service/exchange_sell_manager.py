"""One-shot spot-sale transport shared by trading modes."""

import asyncio
from typing import Any

import ccxt.async_support as ccxt


class ExchangeSellManager:
    """Submit market sales once without lifecycle accounting."""

    def __init__(self, logger: Any, get_exchange: Any):
        self._logger = logger
        self._get_exchange = get_exchange

    async def submit_market_sell_once(
        self, *, symbol: str, amount: str | float, params: dict[str, Any]
    ) -> Any:
        """Submit a journaled market sale once, preserving raw exchange evidence."""
        exchange = self._get_exchange()
        if exchange is None:
            raise RuntimeError("Exchange client is unavailable.")
        client_order_id = params.get("clientOrderId", "unavailable")
        self._logger.info(
            "Submitting journaled sell symbol=%s amount=%s client_order_id=%s",
            symbol,
            amount,
            client_order_id,
        )
        try:
            result = await exchange.create_market_sell_order(symbol, amount, params)
        except (
            asyncio.CancelledError,
            ccxt.BaseError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
        ) as exc:
            self._logger.warning(
                "Journaled sell requires reconciliation symbol=%s client_order_id=%s failure=%s",
                symbol,
                client_order_id,
                type(exc).__name__,
            )
            raise
        self._logger.info(
            "Journaled sell request returned symbol=%s client_order_id=%s",
            symbol,
            client_order_id,
        )
        return result
