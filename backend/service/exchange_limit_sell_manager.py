"""Bounded exchange order observation and cancellation mechanics."""

import asyncio
import math
from collections.abc import Mapping
from typing import Any

import ccxt.async_support as ccxt
from service.exchange_capabilities import ExchangeSubmissionIndeterminate
from service.exchange_types import ExchangeOrderPayload


class ExchangeLimitSellManager:
    """Observe and cancel exchange orders without mode-specific fallback policy."""

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
        if "filled" in exchange_order and exchange_order["filled"] is not None:
            order["filled"] = float(exchange_order["filled"])
        if "remaining" in exchange_order and exchange_order["remaining"] is not None:
            order["remaining"] = float(exchange_order["remaining"])
        if "average" in exchange_order and exchange_order["average"] is not None:
            order["average"] = float(exchange_order["average"])
        if "status" in exchange_order and exchange_order["status"] is not None:
            order["status"] = str(exchange_order["status"])
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
        except ccxt.NetworkError as exc:
            raise ExchangeSubmissionIndeterminate(
                action="cancel",
                symbol=symbol,
                client_order_id=None,
            ) from exc
        except (ccxt.BaseError, RuntimeError, TypeError, ValueError) as exc:
            self._logger.warning(
                "Cancel order %s for %s failed or order is already closed: %s",
                order_id,
                symbol,
                exc,
            )

    async def cancel_order_and_confirm(
        self,
        symbol: str,
        order_id: str,
    ) -> dict[str, Any] | None:
        """Cancel an order and return its final exchange state."""
        exchange = self._get_exchange()
        if exchange is None:
            return None

        await self.cancel_order_safe(symbol, order_id)

        for _ in range(5):
            try:
                latest = await exchange.fetch_order(order_id, symbol)
                order_status = str(latest.get("status", "")).lower()
                if order_status in {
                    "closed",
                    "filled",
                    "canceled",
                    "cancelled",
                    "rejected",
                    "expired",
                }:
                    return latest
            except (ccxt.BaseError, RuntimeError, TypeError, ValueError) as exc:
                self._logger.warning(
                    "Could not verify cancel status for order %s on %s: %s",
                    order_id,
                    symbol,
                    exc,
                )
            await asyncio.sleep(0.5)

        return None

    @staticmethod
    def _explicit_number(payload: Mapping[str, Any], key: str) -> float | None:
        """Return a finite numeric field only when the exchange supplied it."""
        value = payload.get(key)
        if value is None or value == "":
            return None
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"Exchange order field {key!r} is not finite")
        return number

    @staticmethod
    def _cancel_is_filled(
        *,
        status: str,
        filled: float | None,
        amount: float | None,
        remaining: float | None,
    ) -> bool:
        """Return whether final cancel reconciliation proves the order filled."""
        if status in {"closed", "filled"}:
            return True
        if filled is not None and amount is not None and filled >= amount > 0:
            return True
        return (
            filled is not None
            and filled > 0
            and remaining is not None
            and remaining <= 0
        )

    @staticmethod
    def _cancel_quantities_are_consistent(
        *,
        filled: float | None,
        remaining: float | None,
        submitted_amount: float | None,
        reported_amount: float | None,
        precision: int | None,
    ) -> bool:
        """Validate non-negative canceled quantities against the known total."""
        if (
            filled is None
            or remaining is None
            or submitted_amount is None
            or submitted_amount <= 0
        ):
            return False
        if filled < 0 or remaining < 0:
            return False

        precision_digits = max(8, min(precision or 8, 12))
        absolute_tolerance = 10 ** (-precision_digits)
        if reported_amount is not None and not math.isclose(
            reported_amount,
            submitted_amount,
            rel_tol=1e-9,
            abs_tol=absolute_tolerance,
        ):
            return False
        return math.isclose(
            filled + remaining,
            submitted_amount,
            rel_tol=1e-9,
            abs_tol=absolute_tolerance,
        )
