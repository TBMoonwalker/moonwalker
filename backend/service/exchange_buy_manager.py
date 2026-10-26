"""Shared market and price-capped buy submission mechanics."""

import asyncio
import math
from typing import Any, cast

import ccxt.async_support as ccxt
from service.exchange_capabilities import (
    ExchangePostSubmissionFailure,
    ExchangeSubmissionIndeterminate,
    build_client_order_params,
)
from service.exchange_types import ExchangeOrderPayload


class ExchangeBuyManager:
    """Submit buys and retain bounded exchange execution evidence."""

    def __init__(self, logger: Any, get_exchange: Any):
        self._logger = logger
        self._get_exchange = get_exchange

    async def submit_buy_once(
        self,
        *,
        symbol: str,
        order_type: str,
        amount: float | str,
        price: float | str,
        params: dict[str, Any],
    ) -> Any:
        """Submit once, retaining raw evidence for the owning lifecycle.

        No retry, cancellation or accounting is performed here. Callers journal
        uncertainty if transport fails after they claim submission.
        """
        exchange = self._get_exchange()
        if exchange is None:
            raise RuntimeError("Exchange client is unavailable.")
        client_order_id = params.get(
            "clientOrderId", params.get("newClientOrderId", "unavailable")
        )
        self._logger.info(
            "Submitting journaled buy symbol=%s type=%s amount=%s price=%s client_order_id=%s",
            symbol,
            order_type,
            amount,
            price,
            client_order_id,
        )
        try:
            result = await exchange.create_order(
                symbol, order_type, "buy", amount, price, params
            )
        except asyncio.CancelledError:
            self._logger.warning(
                "Journaled buy requires reconciliation symbol=%s client_order_id=%s failure=CancelledError",
                symbol,
                client_order_id,
            )
            raise
        except (
            ccxt.BaseError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
        ) as exc:
            self._logger.warning(
                "Journaled buy requires reconciliation symbol=%s client_order_id=%s failure=%s",
                symbol,
                client_order_id,
                type(exc).__name__,
            )
            raise
        self._logger.info(
            "Journaled buy request returned symbol=%s client_order_id=%s",
            symbol,
            client_order_id,
        )
        return result

    async def execute_market_buy(
        self, order: ExchangeOrderPayload
    ) -> ExchangeOrderPayload | None:
        """Place a market buy or a price-capped IOC recovery buy."""
        exchange = self._get_exchange()
        if exchange is None:
            return None

        try:
            self._logger.info("Try to buy %s %s", order["amount"], order["symbol"])
            maximum_buy_price = float(order.get("maximum_buy_price") or 0.0)
            order_type = order["ordertype"]
            order_price = order["price"]
            params: dict[str, Any] = build_client_order_params(
                order.get("client_order_id")
            )
            if maximum_buy_price > 0:
                order_type = "limit"
                order_price = exchange.price_to_precision(
                    order["symbol"],
                    maximum_buy_price,
                )
                params["timeInForce"] = "IOC"
                self._logger.info(
                    "Using capped IOC recovery buy for %s at maximum price %s.",
                    order["symbol"],
                    order_price,
                )
            trade = await self.submit_buy_once(
                symbol=order["symbol"],
                order_type=order_type,
                amount=order["amount"],
                price=order_price,
                params=params,
            )
            if not isinstance(trade, dict):
                raise ExchangePostSubmissionFailure(
                    action="buy",
                    symbol=str(order["symbol"]),
                    order=order,
                    cause=TypeError("Exchange returned a non-object order result"),
                    operation_id=str(order.get("operation_id") or "") or None,
                )
            if (
                maximum_buy_price > 0
                and getattr(exchange, "id", None) in {"bybit", "bybiteu"}
                and trade.get("filled") in (None, "")
            ):
                try:
                    trade = await self._resolve_bybit_ioc(exchange, order, trade)
                except (
                    ccxt.BaseError,
                    TimeoutError,
                    OSError,
                    TypeError,
                    ValueError,
                    RuntimeError,
                    KeyError,
                    AttributeError,
                ) as exc:
                    raise ExchangePostSubmissionFailure(
                        action="buy",
                        symbol=str(order["symbol"]),
                        order={**order, **trade},
                        cause=exc,
                        operation_id=str(order.get("operation_id") or "") or None,
                    ) from exc
            try:
                order.update(cast(ExchangeOrderPayload, trade))
            except (TypeError, ValueError, RuntimeError, KeyError) as exc:
                raise ExchangePostSubmissionFailure(
                    action="buy",
                    symbol=str(order["symbol"]),
                    order={**order, **trade},
                    cause=exc,
                    operation_id=str(order.get("operation_id") or "") or None,
                ) from exc
            if maximum_buy_price > 0:
                order["ordertype"] = "limit"
                try:
                    raw_filled_amount = trade.get("filled")
                    if raw_filled_amount is None or raw_filled_amount == "":
                        raise ValueError(
                            "Capped buy response omitted explicit fill evidence"
                        )
                    filled_amount = float(raw_filled_amount)
                    if not math.isfinite(filled_amount) or filled_amount < 0:
                        raise ValueError(
                            "Capped buy response returned invalid fill evidence"
                        )
                    status = str(trade.get("status") or "").lower()
                except (TypeError, ValueError, RuntimeError, KeyError) as exc:
                    raise ExchangePostSubmissionFailure(
                        action="buy",
                        symbol=str(order["symbol"]),
                        order=order,
                        cause=exc,
                        operation_id=str(order.get("operation_id") or "") or None,
                    ) from exc
                if filled_amount <= 0:
                    order_id = trade.get("id")
                    if order_id and status == "open":
                        try:
                            await exchange.cancel_order(order_id, order["symbol"])
                        except ccxt.NetworkError as exc:
                            raise ExchangeSubmissionIndeterminate(
                                action="cancel_unfilled_buy",
                                symbol=str(order["symbol"]),
                                client_order_id=str(order.get("client_order_id") or "")
                                or None,
                            ) from exc
                        except ccxt.BaseError as exc:
                            raise ExchangePostSubmissionFailure(
                                action="cancel_unfilled_buy",
                                symbol=str(order["symbol"]),
                                order=order,
                                cause=exc,
                                operation_id=str(order.get("operation_id") or "")
                                or None,
                            ) from exc
                    elif status in {"closed", "filled"}:
                        raise ExchangePostSubmissionFailure(
                            action="buy",
                            symbol=str(order["symbol"]),
                            order=order,
                            cause=RuntimeError(
                                "Capped buy returned a filled terminal status with "
                                "an explicit zero fill"
                            ),
                            operation_id=str(order.get("operation_id") or "") or None,
                        )
                    elif status not in {
                        "canceled",
                        "cancelled",
                        "rejected",
                        "expired",
                    }:
                        raise ExchangePostSubmissionFailure(
                            action="buy",
                            symbol=str(order["symbol"]),
                            order=order,
                            cause=RuntimeError(
                                "Unfilled capped buy did not return a definitive "
                                "terminal status or cancelable exchange order id"
                            ),
                            operation_id=str(order.get("operation_id") or "") or None,
                        )
                    self._logger.info(
                        "Capped recovery buy for %s did not fill at or below %s.",
                        order["symbol"],
                        order_price,
                    )
                    return None
            return order
        except (ccxt.InvalidOrder, ccxt.BadRequest):
            # A rejected submission is distinct from an accepted IOC with no fill.
            raise
        except ccxt.ExchangeError as exc:
            self._logger.error(
                "Buying pair %s failed due to an exchange error: %s",
                order["symbol"],
                exc,
            )
            return None
        except ccxt.NetworkError as exc:
            raise ExchangeSubmissionIndeterminate(
                action="buy",
                symbol=str(order["symbol"]),
                client_order_id=str(order.get("client_order_id") or "") or None,
            ) from exc
        except ExchangePostSubmissionFailure:
            raise
        except ccxt.BaseError as exc:
            self._logger.error(
                "Buying pair %s failed due to an error: %s", order["symbol"], exc
            )
            return None
        except (TypeError, ValueError, RuntimeError, KeyError) as exc:
            self._logger.error("Buying pair %s failed with: %s", order["symbol"], exc)
            return None

    async def _resolve_bybit_ioc(
        self,
        exchange: Any,
        order: ExchangeOrderPayload,
        acknowledgement: dict[str, Any],
    ) -> dict[str, Any]:
        """Read an acknowledged IOC to terminal status without resubmitting it."""
        order_id = str(acknowledgement.get("id") or "")
        if not order_id:
            raise ValueError("Acknowledged IOC has no exchange order identity")
        async with asyncio.timeout(5):
            for attempt in range(3):
                try:
                    result = await exchange.fetch_order(order_id, order["symbol"])
                except ccxt.OrderNotFound:
                    result = None
                if isinstance(result, dict):
                    if str(result.get("id") or "") != order_id or (
                        result.get("symbol") is not None
                        and result["symbol"] != order["symbol"]
                    ):
                        raise ValueError("IOC lookup returned a different order")
                    status = str(result.get("status") or "").lower()
                    if result.get("filled") is not None and status in {
                        "closed",
                        "filled",
                        "canceled",
                        "cancelled",
                        "rejected",
                        "expired",
                    }:
                        return {**acknowledgement, **result}
                if attempt < 2:
                    await asyncio.sleep(0.2)
        raise ValueError("Acknowledged IOC still has no terminal fill evidence")
