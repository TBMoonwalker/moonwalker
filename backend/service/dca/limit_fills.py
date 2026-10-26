"""Limit sell polling and fallback orchestration helpers."""

from typing import Any

import ccxt.async_support as ccxt
from service.dca.limit_sell import (
    build_market_fallback_status,
    get_limit_sell_timeout_seconds,
)
from service.exchange_capabilities import ExchangeSubmissionIndeterminate
from service.exchange_contexts import LimitSellFillContext
from service.exchange_limit_sell_manager import ExchangeLimitSellManager
from service.exchange_types import ExchangeOrderPayload


class DcaLimitSellManager(ExchangeLimitSellManager):
    """DCA-specific policy using the shared exchange mechanics."""

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
                            **(
                                {"metadata_json": partial_fill_status["metadata_json"]}
                                if partial_fill_status.get("metadata_json")
                                else {}
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
