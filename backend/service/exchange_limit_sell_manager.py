"""Limit sell polling and fallback orchestration helpers."""

import asyncio
import math
from collections.abc import Mapping
from typing import Any

import ccxt.async_support as ccxt
from service.exchange_capabilities import ExchangeSubmissionIndeterminate
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
                try:
                    latest_filled = self._explicit_number(
                        latest_order_status,
                        "filled",
                    )
                    latest_amount = self._explicit_number(
                        latest_order_status,
                        "amount",
                    )
                    latest_remaining = self._explicit_number(
                        latest_order_status,
                        "remaining",
                    )
                    latest_status = str(latest_order_status.get("status") or "").lower()
                except (TypeError, ValueError):
                    latest_filled = None
                    latest_amount = None
                    latest_remaining = None
                    latest_status = ""

                if self._cancel_is_filled(
                    status=latest_status,
                    filled=latest_filled,
                    amount=latest_amount,
                    remaining=latest_remaining,
                ):
                    self._merge_exchange_order_fields(
                        sell_order,
                        latest_order_status,
                    )
                    return await context.build_sell_order_status(sell_order)

                if latest_filled is not None and latest_filled > 0:
                    self._logger.info(
                        "Limit sell for %s partially filled before timeout. "
                        "filled=%s remaining=%s",
                        resolved_symbol,
                        latest_filled,
                        latest_remaining,
                    )

            self._logger.info(
                "Limit sell for %s was not filled within %s seconds.",
                resolved_symbol,
                timeout_seconds,
            )
            cancel_status = await self.cancel_order_and_confirm(
                resolved_symbol,
                str(sell_order["id"]),
            )
            if cancel_status is None:
                self._logger.error(
                    "Limit order %s for %s was not filled but could not be "
                    "confirmed canceled. Skipping market fallback.",
                    sell_order["id"],
                    resolved_symbol,
                )
                raise ExchangeSubmissionIndeterminate(
                    action="cancel",
                    symbol=resolved_symbol,
                    client_order_id=(
                        str(original_order.get("client_order_id") or "") or None
                    ),
                )

            try:
                final_status = str(cancel_status.get("status") or "").lower()
                final_filled = self._explicit_number(cancel_status, "filled")
                final_amount = self._explicit_number(cancel_status, "amount")
                final_remaining = self._explicit_number(cancel_status, "remaining")
                submitted_amount = None
                for payload in (sell_order, original_order):
                    for key in ("total_amount", "amount"):
                        submitted_amount = self._explicit_number(payload, key)
                        if submitted_amount is not None:
                            break
                    if submitted_amount is not None:
                        break
            except (TypeError, ValueError) as exc:
                self._logger.error(
                    "Final cancel state for limit order %s on %s is malformed: %s",
                    sell_order["id"],
                    resolved_symbol,
                    exc,
                )
                raise ExchangeSubmissionIndeterminate(
                    action="cancel",
                    symbol=resolved_symbol,
                    client_order_id=(
                        str(original_order.get("client_order_id") or "") or None
                    ),
                ) from exc

            if final_status in {"canceled", "cancelled"}:
                raw_precision = sell_order.get("precision")
                try:
                    quantity_precision = (
                        int(raw_precision) if raw_precision is not None else None
                    )
                except (TypeError, ValueError):
                    quantity_precision = None
                if not self._cancel_quantities_are_consistent(
                    filled=final_filled,
                    remaining=final_remaining,
                    submitted_amount=submitted_amount,
                    reported_amount=final_amount,
                    precision=quantity_precision,
                ):
                    self._logger.error(
                        "Canceled limit order %s for %s returned inconsistent "
                        "filled, remaining, and amount evidence. Skipping market "
                        "fallback.",
                        sell_order["id"],
                        resolved_symbol,
                    )
                    raise ExchangeSubmissionIndeterminate(
                        action="cancel",
                        symbol=resolved_symbol,
                        client_order_id=(
                            str(original_order.get("client_order_id") or "") or None
                        ),
                    )

            self._merge_exchange_order_fields(sell_order, cancel_status)
            if self._cancel_is_filled(
                status=final_status,
                filled=final_filled,
                amount=final_amount,
                remaining=final_remaining,
            ):
                self._logger.info(
                    "Limit sell for %s filled while cancellation was in flight.",
                    resolved_symbol,
                )
                return await context.build_sell_order_status(sell_order)

            if (
                final_status not in {"canceled", "cancelled"}
                or final_filled is None
                or final_remaining is None
            ):
                self._logger.error(
                    "Limit order %s for %s did not return an explicit canceled "
                    "state with fill evidence. Skipping market fallback.",
                    sell_order["id"],
                    resolved_symbol,
                )
                raise ExchangeSubmissionIndeterminate(
                    action="cancel",
                    symbol=resolved_symbol,
                    client_order_id=(
                        str(original_order.get("client_order_id") or "") or None
                    ),
                )

            original_order["_limit_cancel_confirmed"] = True

            if final_filled > 0:
                partial_fill_status = await context.parse_order_status(sell_order)
                partial_price = float(
                    partial_fill_status.get("price")
                    or cancel_status.get("average")
                    or cancel_status.get("price")
                    or 0.0
                )
                return build_market_fallback_status(
                    symbol=resolved_symbol,
                    exchange_order_id=str(sell_order["id"]),
                    remaining_amount=final_remaining,
                    partial_filled_amount=final_filled,
                    partial_avg_price=partial_price,
                    executions=[
                        {
                            "symbol": resolved_symbol,
                            "side": str(partial_fill_status.get("side") or "sell"),
                            "role": "partial_sell",
                            "timestamp": str(
                                partial_fill_status.get("timestamp")
                                or sell_order.get("timestamp")
                                or ""
                            ),
                            "price": partial_price,
                            "amount": final_filled,
                            "ordersize": float(
                                partial_fill_status.get("ordersize")
                                or final_filled * partial_price
                            ),
                            "fee": float(
                                partial_fill_status.get("base_fee")
                                or partial_fill_status.get("amount_fee")
                                or 0.0
                            ),
                            "order_id": str(
                                partial_fill_status.get("orderid") or sell_order["id"]
                            ),
                            "order_type": str(sell_order.get("ordertype") or "limit"),
                        }
                    ],
                    fallback_reason="limit_order_partial_timeout",
                )

            return build_market_fallback_status(
                symbol=resolved_symbol,
                exchange_order_id=str(sell_order["id"]),
                remaining_amount=final_remaining,
                limit_cancel_confirmed=bool(
                    original_order.get("_limit_cancel_confirmed", True)
                ),
                fallback_reason="limit_order_timeout",
            )

        self._merge_exchange_order_fields(sell_order, filled_order)
        self._logger.info("Limit sell for %s filled.", resolved_symbol)
        return await context.build_sell_order_status(sell_order)
