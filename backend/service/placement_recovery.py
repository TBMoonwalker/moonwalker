"""Resume local order persistence from reconciled exchange evidence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from service.exchange_types import ExchangeOrderPayload, SoldCheckStatus
from service.placement_intents import (
    PlacementAction,
    deserialize_placement_payload,
)

ValidatePayload = Callable[[dict[str, Any]], bool]
FinalizeBuy = Callable[..., Awaitable[bool]]
FinalizeSell = Callable[..., Awaitable[None]]
BuildSellPayload = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
PersistLimitFallback = Callable[
    [dict[str, Any], dict[str, Any], str],
    Awaitable[bool],
]


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
    ) -> bool:
        """Resume one confirmed effect without placing another exchange order."""
        operation_id = str(intent.operation_id)
        request = deserialize_placement_payload(intent.request_json)
        stored_result = deserialize_placement_payload(intent.result_json)
        evidence = dict(exchange_order or stored_result)
        action = str(intent.action)

        if action == PlacementAction.BUY.value:
            return await self._resume_buy(
                operation_id,
                request,
                evidence,
                config,
            )
        if action == PlacementAction.SELL.value:
            return await self._resume_sell(
                operation_id,
                request,
                evidence,
                config,
            )
        if action == PlacementAction.LIMIT_SELL.value:
            return await self._resume_limit_sell(
                intent,
                operation_id,
                request,
                evidence,
                config,
            )
        if action == PlacementAction.CANCEL.value:
            return await self._resume_cancel(
                intent,
                operation_id,
                evidence,
                config,
            )
        return False

    async def _resume_buy(
        self,
        operation_id: str,
        request: dict[str, Any],
        evidence: dict[str, Any],
        config: dict[str, Any],
    ) -> bool:
        """Normalize and persist a confirmed buy fill."""
        normalized = (
            {**request, **evidence}
            if evidence.get("fees") is not None
            and evidence.get("precision") is not None
            else await self.exchange.build_spot_buy_order_status(
                evidence,
                request,
                config,
            )
        )
        if not normalized or not self.validate_buy(normalized):
            return False
        return bool(
            await self.finalize_buy(
                cast(ExchangeOrderPayload, normalized),
                config,
                original_order=request,
                placement_operation_id=operation_id,
            )
        )

    async def _resume_sell(
        self,
        operation_id: str,
        request: dict[str, Any],
        evidence: dict[str, Any],
        config: dict[str, Any],
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
        await self.finalize_sell(
            cast(SoldCheckStatus, normalized),
            config,
            placement_operation_id=operation_id,
        )
        return True

    async def _resume_limit_sell(
        self,
        intent: Any,
        operation_id: str,
        request: dict[str, Any],
        evidence: dict[str, Any],
        config: dict[str, Any],
    ) -> bool:
        """Persist either an open proactive order or its confirmed fill."""
        if bool(evidence.get("requires_market_fallback")):
            return await self.persist_limit_fallback(
                evidence,
                config,
                operation_id,
            )
        if str(evidence.get("status") or "").lower() == "open":
            order_id = str(evidence.get("id") or intent.exchange_order_id or "")
            price = float(
                evidence.get("price")
                or request.get("limit_price")
                or intent.maximum_price
                or 0.0
            )
            amount = float(
                evidence.get("amount")
                or request.get("total_amount")
                or intent.requested_amount
                or 0.0
            )
            return bool(
                await self.trades.set_tp_limit_order(
                    str(intent.symbol),
                    order_id=order_id,
                    price=price,
                    amount=amount,
                    placement_operation_id=operation_id,
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
        await self.finalize_sell(
            cast(SoldCheckStatus, normalized),
            config,
            placement_operation_id=operation_id,
        )
        return True

    async def _resume_cancel(
        self,
        intent: Any,
        operation_id: str,
        evidence: dict[str, Any],
        config: dict[str, Any],
    ) -> bool:
        """Persist a confirmed cancel and any exchange-reported partial fill."""
        symbol = str(intent.symbol)
        status = str(evidence.get("status") or "").lower()
        filled = float(evidence.get("filled") or 0.0)
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
            await self.finalize_sell(
                cast(SoldCheckStatus, normalized),
                config,
                placement_operation_id=operation_id,
            )
            return True

        return bool(
            await self.trades.clear_tp_limit_order(
                symbol,
                placement_operation_id=operation_id,
                exchange_status=evidence,
            )
        )
