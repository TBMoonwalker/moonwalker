"""Resume local order persistence from reconciled exchange evidence."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from service.exchange_types import ExchangeOrderPayload, SoldCheckStatus
from service.placement_intents import (
    BUY_RECOVERY_CONTEXT_KEYS,
    PlacementAction,
    QuarantineResolution,
    RecoveryTarget,
    deserialize_placement_payload,
)
from service.placement_repair import (
    has_terminal_partial_sell,
    has_valid_stored_partial_sell,
)

ValidatePayload = Callable[[dict[str, Any]], bool]
FinalizeBuy = Callable[..., Awaitable[bool]]
FinalizeSell = Callable[..., Awaitable[None]]
BuildSellPayload = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
PersistLimitFallback = Callable[..., Awaitable[bool]]


def _positive_finite(value: Any) -> float | None:
    """Return a usable order value without accepting invalid exchange data."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _matches_intent(payload: dict[str, Any], intent: Any) -> bool:
    """Reject evidence that explicitly identifies another symbol or side."""
    symbol = payload.get("symbol")
    side = payload.get("side")
    expected_side = "buy" if str(intent.action) == PlacementAction.BUY.value else "sell"
    return (symbol is None or symbol == intent.symbol) and (
        side is None or str(side).strip().lower() == expected_side
    )


def _valid_full_sell(
    payload: dict[str, Any], evidence: dict[str, Any], intent: Any
) -> bool:
    """Validate normalized full-sell values before any trade can close."""
    if not _matches_intent(payload, intent):
        return False
    amount = _positive_finite(payload.get("total_amount"))
    price = _positive_finite(payload.get("price"))
    cost = _positive_finite(payload.get("total_cost"))
    if amount is None or price is None or cost is None:
        return False
    filled = evidence.get("filled")
    if filled is not None:
        actual = _positive_finite(filled)
        if actual is None or not math.isclose(amount, actual, rel_tol=1e-12):
            return False
    proceeds = amount * price
    if not math.isfinite(proceeds) or proceeds <= 0:
        return False
    if evidence.get("cost") is not None:
        exchange_cost = _positive_finite(evidence.get("cost"))
        if exchange_cost is None or not math.isclose(
            proceeds, exchange_cost, rel_tol=1e-8, abs_tol=0.0
        ):
            return False
    if evidence.get("average") is not None:
        average = _positive_finite(evidence.get("average"))
        if average is None or not math.isclose(
            price, average, rel_tol=1e-8, abs_tol=0.0
        ):
            return False
    return True


@dataclass(frozen=True)
class PlacementRecoveryHandler:
    """Map reconciled exchange results back into atomic business persistence."""

    exchange: Any
    trades: Any
    validate_buy: ValidatePayload
    validate_sell: ValidatePayload
    finalize_buy: FinalizeBuy
    finalize_sell: FinalizeSell
    build_limit_sell_payload: BuildSellPayload
    persist_limit_fallback: PersistLimitFallback

    async def resume(
        self,
        intent: Any,
        exchange_order: dict[str, Any],
        config: dict[str, Any],
        *,
        resolution: QuarantineResolution | None = None,
    ) -> bool:
        """Resume one confirmed effect without placing another exchange order."""
        operation_id = str(intent.operation_id)
        request = deserialize_placement_payload(intent.request_json)
        stored_result = deserialize_placement_payload(intent.result_json)
        evidence = dict(exchange_order or stored_result)
        action = str(intent.action)
        recovery_target = None
        if resolution is None:
            recovery_target = RecoveryTarget(
                operation_id=operation_id,
                request_json=str(intent.request_json),
                symbol=str(intent.symbol),
                action=action,
                deal_id=str(intent.deal_id)
                if getattr(intent, "deal_id", None)
                else None,
                exchange_order_id=str(
                    evidence.get("id") or intent.exchange_order_id or ""
                )
                or None,
                client_order_id=str(intent.client_order_id)
                if getattr(intent, "client_order_id", None)
                else None,
                base_buy=action == PlacementAction.BUY.value
                and bool(request.get("baseorder")),
            )
        if not _matches_intent(evidence, intent):
            return False

        if action in {
            PlacementAction.SELL.value,
            PlacementAction.LIMIT_SELL.value,
        } and has_valid_stored_partial_sell(intent, evidence):
            partial = dict(evidence)
            partial["recovery_deal_id"] = str(intent.deal_id)
            partial["recovery_tp_order_id"] = (
                str(intent.exchange_order_id)
                if action == PlacementAction.LIMIT_SELL.value
                else None
            )
            return bool(
                await self.persist_limit_fallback(
                    partial,
                    config,
                    operation_id,
                    **({"resolution": resolution} if resolution else {}),
                )
            )

        if action in {
            PlacementAction.SELL.value,
            PlacementAction.LIMIT_SELL.value,
        } and has_terminal_partial_sell(intent, evidence):
            filled = float(evidence["filled"])
            cost = _positive_finite(evidence.get("cost"))
            average = _positive_finite(evidence.get("average"))
            if cost is None and average is not None:
                cost = filled * average
            if cost is None or not math.isfinite(cost) or cost <= 0:
                return False
            execution_price = cost / filled
            if not math.isfinite(execution_price) or execution_price <= 0:
                return False
            return bool(
                await self.persist_limit_fallback(
                    {
                        "symbol": str(intent.symbol),
                        "partial_filled_amount": filled,
                        "partial_avg_price": execution_price,
                        "remaining_amount": float(intent.requested_amount) - filled,
                        "executions": [
                            {
                                "symbol": str(intent.symbol),
                                "side": "sell",
                                "role": "partial_sell",
                                "timestamp": str(evidence.get("timestamp") or ""),
                                "price": execution_price,
                                "amount": filled,
                                "ordersize": cost,
                                "order_id": str(
                                    evidence.get("id") or intent.exchange_order_id or ""
                                ),
                            }
                        ],
                        "recovery_deal_id": str(intent.deal_id or ""),
                        "recovery_tp_order_id": str(evidence.get("id") or "")
                        if action == PlacementAction.LIMIT_SELL.value
                        else None,
                    },
                    config,
                    operation_id,
                    **({"resolution": resolution} if resolution else {}),
                )
            )

        if action == PlacementAction.BUY.value:
            # Older intents omitted local context from request_json. Their
            # accepted result can still carry it even when lookup returns raw
            # exchange evidence with no Moonwalker fields.
            for key in BUY_RECOVERY_CONTEXT_KEYS:
                if key not in request and key in stored_result:
                    request[key] = stored_result[key]
            return await self._resume_buy(
                operation_id,
                request,
                evidence,
                config,
                intent=intent,
                resolution=resolution,
                recovery_target=recovery_target,
            )
        if action == PlacementAction.SELL.value:
            return await self._resume_sell(
                operation_id,
                request,
                evidence,
                config,
                intent=intent,
                resolution=resolution,
                recovery_target=recovery_target,
            )
        if action == PlacementAction.LIMIT_SELL.value:
            return await self._resume_limit_sell(
                intent,
                operation_id,
                request,
                evidence,
                config,
                resolution=resolution,
                recovery_target=recovery_target,
            )
        if action == PlacementAction.CANCEL.value:
            return await self._resume_cancel(
                intent,
                operation_id,
                evidence,
                config,
                resolution=resolution,
                recovery_target=recovery_target,
            )
        return False

    async def _resume_buy(
        self,
        operation_id: str,
        request: dict[str, Any],
        evidence: dict[str, Any],
        config: dict[str, Any],
        *,
        intent: Any,
        resolution: QuarantineResolution | None = None,
        recovery_target: RecoveryTarget | None = None,
    ) -> bool:
        """Normalize and persist a confirmed buy fill."""
        if request.get("safetyorder") and request.get("so_percentage") is None:
            raise ValueError(
                "Legacy safety-order intent is missing so_percentage; "
                "restore the original value before retrying reconciliation."
            )
        request.setdefault("so_percentage", None)
        normalized_evidence = resolution is None or (
            isinstance(evidence.get("amount"), (int, float))
            and not isinstance(evidence.get("amount"), bool)
            and evidence.get("amount") == evidence.get("filled")
            and evidence.get("ordersize") is not None
        )
        normalized = (
            {**request, **evidence}
            if evidence.get("fees") is not None
            and evidence.get("precision") is not None
            and normalized_evidence
            else await self.exchange.build_spot_buy_order_status(
                evidence,
                request,
                config,
            )
        )
        if (
            not normalized
            or not self.validate_buy(normalized)
            or not _matches_intent(normalized, intent)
        ):
            return False
        normalized_amount = _positive_finite(normalized.get("amount"))
        normalized_price = _positive_finite(normalized.get("price"))
        normalized_cost = _positive_finite(normalized.get("ordersize"))
        if (
            normalized_amount is None
            or normalized_price is None
            or normalized_cost is None
            or not math.isfinite(normalized_amount * normalized_price)
        ):
            return False
        if evidence.get("filled") is not None:
            filled = _positive_finite(evidence.get("filled"))
            try:
                fee = float(normalized.get("amount_fee") or 0)
            except (TypeError, ValueError):
                return False
            if (
                filled is None
                or not math.isfinite(fee)
                or fee < 0
                or not math.isclose(normalized_amount + fee, filled, rel_tol=1e-12)
            ):
                return False
        for key in BUY_RECOVERY_CONTEXT_KEYS:
            if key not in normalized and key in request:
                normalized[key] = request[key]
        return bool(
            await self.finalize_buy(
                cast(ExchangeOrderPayload, normalized),
                config,
                original_order=request,
                placement_operation_id=operation_id,
                **({"resolution": resolution} if resolution else {}),
                **({"recovery_target": recovery_target} if recovery_target else {}),
            )
        )

    async def _resume_sell(
        self,
        operation_id: str,
        request: dict[str, Any],
        evidence: dict[str, Any],
        config: dict[str, Any],
        *,
        intent: Any,
        resolution: QuarantineResolution | None = None,
        recovery_target: RecoveryTarget | None = None,
    ) -> bool:
        """Normalize and persist a confirmed market sell fill."""
        normalized = {**request, **evidence}
        if not self.validate_sell(normalized):
            rebuilt = await self.exchange.build_spot_sell_order_status(
                normalized,
                config,
            )
            if not rebuilt or not self.validate_sell(rebuilt):
                return False
            normalized = rebuilt
        if not _valid_full_sell(normalized, evidence, intent):
            return False
        await self.finalize_sell(
            cast(SoldCheckStatus, normalized),
            config,
            placement_operation_id=operation_id,
            **({"resolution": resolution} if resolution else {}),
            **({"recovery_target": recovery_target} if recovery_target else {}),
        )
        return True

    async def _resume_limit_sell(
        self,
        intent: Any,
        operation_id: str,
        request: dict[str, Any],
        evidence: dict[str, Any],
        config: dict[str, Any],
        *,
        resolution: QuarantineResolution | None = None,
        recovery_target: RecoveryTarget | None = None,
    ) -> bool:
        """Persist either an open proactive order or its confirmed fill."""
        if bool(evidence.get("requires_market_fallback")):
            return await self.persist_limit_fallback(
                evidence,
                config,
                operation_id,
                **({"resolution": resolution} if resolution else {}),
            )
        if str(evidence.get("status") or "").lower() == "open":
            order_id = str(evidence.get("id") or intent.exchange_order_id or "").strip()
            requested = _positive_finite(intent.requested_amount) or _positive_finite(
                request.get("total_amount")
            )
            raw_price = evidence.get("price")
            if raw_price is None:
                raw_price = request.get("limit_price") or intent.maximum_price
            raw_amount = evidence.get("amount")
            if raw_amount is None:
                raw_amount = request.get("total_amount") or intent.requested_amount
            price = _positive_finite(raw_price)
            amount = _positive_finite(raw_amount)
            if not order_id or price is None or amount is None or requested is None:
                return False
            if amount > requested and not math.isclose(amount, requested, rel_tol=1e-9):
                return False
            return bool(
                await self.trades.set_tp_limit_order(
                    str(intent.symbol),
                    order_id=order_id,
                    price=price,
                    amount=amount,
                    placement_operation_id=operation_id,
                    **({"resolution": resolution} if resolution else {}),
                    **({"recovery_target": recovery_target} if recovery_target else {}),
                )
            )

        trade_data = await self.trades.get_trades_for_orders(str(intent.symbol))
        if not trade_data:
            return False
        payload = self.build_limit_sell_payload(trade_data, evidence)
        normalized = await self.exchange.build_spot_sell_order_status(
            payload,
            config,
        )
        if not normalized or not self.validate_sell(normalized):
            return False
        if not _valid_full_sell(normalized, evidence, intent):
            return False
        await self.finalize_sell(
            cast(SoldCheckStatus, normalized),
            config,
            placement_operation_id=operation_id,
            **({"resolution": resolution} if resolution else {}),
            **({"recovery_target": recovery_target} if recovery_target else {}),
        )
        return True

    async def _resume_cancel(
        self,
        intent: Any,
        operation_id: str,
        evidence: dict[str, Any],
        config: dict[str, Any],
        *,
        resolution: QuarantineResolution | None = None,
        recovery_target: RecoveryTarget | None = None,
    ) -> bool:
        """Persist a confirmed cancel and any exchange-reported partial fill."""
        symbol = str(intent.symbol)
        status = str(evidence.get("status") or "").lower()
        filled = float(evidence.get("filled") or 0.0)
        if evidence.get("amount") is None:
            amount = _positive_finite(intent.requested_amount)
            if amount is None and filled > 0:
                return False
            amount = amount or 0.0
        else:
            amount = float(evidence.get("amount") or 0.0)
        is_filled = status in {"closed", "filled"} or (amount > 0 and filled >= amount)
        if is_filled:
            trade_data = await self.trades.get_trades_for_orders(symbol)
            if not trade_data:
                return False
            payload = self.build_limit_sell_payload(trade_data, evidence)
            normalized = await self.exchange.build_spot_sell_order_status(
                payload,
                config,
            )
            if not normalized or not self.validate_sell(normalized):
                return False
            if not _valid_full_sell(normalized, evidence, intent):
                return False
            await self.finalize_sell(
                cast(SoldCheckStatus, normalized),
                config,
                placement_operation_id=operation_id,
                **({"resolution": resolution} if resolution else {}),
                **({"recovery_target": recovery_target} if recovery_target else {}),
            )
            return True

        return bool(
            await self.trades.clear_tp_limit_order(
                symbol,
                placement_operation_id=operation_id,
                exchange_status=evidence,
                recovery=True,
                recovery_deal_id=getattr(intent, "deal_id", None),
                recovery_tp_order_id=str(
                    evidence.get("id") or intent.exchange_order_id or ""
                ),
                **({"resolution": resolution} if resolution else {}),
            )
        )
