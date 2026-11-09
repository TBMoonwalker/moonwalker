"""Classic-DCA order execution lifecycle: buys, sells, TP limits, manual ops.

Owns the DCA execution entry points (receive_* / arm / cancel / reconcile /
stop / manual) and the durable placement-intent transitions behind them.
Trade finalization lives in service/dca/finalization.py; lifecycle routing
(ownership guard, snapshot validation, operator mutation results) lives in
service/order_routing.py.
"""

import json
import math
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import helper
from service.ai_trust import evaluate_entry_enforcement
from service.capital_budget import CapitalBudgetService
from service.dca.exchange import DcaExchange
from service.dca.finalization import (
    DcaFinalizationContext,
    build_entry_size_retry_order,
    build_tp_limit_sell_payload,
    calculate_closed_trade_stats,
    finalize_buy_order,
    finalize_completed_sell,
    handle_partial_sell_status,
    has_valid_buy_fill,
    is_exchange_order_filled,
    is_exchange_order_inactive,
    is_partial_sell_status,
    is_sold_check_status,
    log_buy_failure,
    persist_reconciled_limit_fallback,
)
from service.dca.limit_sell import build_partial_status_from_fallback
from service.delisting_protection import DelistingProtectionService
from service.exchange_capabilities import (
    ExchangePostSubmissionFailure,
    ExchangeSubmissionIndeterminate,
)
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.lifecycle_snapshot import (
    LifecycleSnapshotIdentity,
    snapshots_match,
)
from service.monitoring import MonitoringService
from service.order_intents import (
    build_manual_buy_order_intent,
    build_manual_sell_order_intent,
)
from service.order_mutation_result import (
    OrderMutationResult,
    OrderMutationStatus,
)
from service.order_payloads import (
    build_manual_buy_open_trade_payload,
    build_manual_buy_trade_payload,
)
from service.order_persistence import persist_closed_trade, persist_manual_buy_add
from service.order_requests import normalize_order_symbol, parse_manual_buy_add_request
from service.order_routing import OrderLifecycleRouting
from service.placement_intents import (
    PlacementAction,
    PlacementIntentState,
    build_derived_operation_id,
    ensure_operation_id,
    is_exchange_placement_enabled,
    is_terminal_placement_state,
)
from service.placement_reconciliation import PlacementReconciler
from service.placement_recovery import PlacementRecoveryHandler
from service.placement_workflow import PlacementWorkflow
from service.sell_fallback_workflow import DurableSellFallback
from service.trade_math import calculate_order_size, calculate_so_percentage
from service.trades import Trades, TradeStateUnavailableError
from service.trading_contracts import BuyIntent, SellIntent
from service.trading_controls import evaluate_buy_like_gate
from tortoise.exceptions import BaseORMException, ConfigurationError

logging = helper.LoggerFactory.get_logger("logs/dca.log", "dca")


@dataclass(frozen=True)
class DefaultOrderCollaborators:
    """The default collaborator set shared by both construction paths."""

    utils: helper.Utils
    capital_budget: CapitalBudgetService
    delisting_protection: DelistingProtectionService
    exchange: DcaExchange
    monitoring: MonitoringService
    placement_workflow: PlacementWorkflow
    trades: Trades


def build_default_order_collaborators() -> DefaultOrderCollaborators:
    """Build the default order collaborators from the single wiring list."""
    return DefaultOrderCollaborators(
        utils=helper.Utils(),
        capital_budget=CapitalBudgetService(),
        delisting_protection=DelistingProtectionService.shared(),
        exchange=DcaExchange(),
        monitoring=MonitoringService(),
        placement_workflow=PlacementWorkflow(),
        trades=Trades(),
    )


class DcaOrderLifecycle:
    """Execute classic-DCA orders: buys, sells, TP limits, manual ops, stops."""

    def __init__(
        self,
        *,
        exchange: DcaExchange | None = None,
        trades: Trades | None = None,
        monitoring: MonitoringService | None = None,
        capital_budget: CapitalBudgetService | None = None,
        delisting_protection: DelistingProtectionService | None = None,
        utils: helper.Utils | None = None,
        placement_workflow: PlacementWorkflow | None = None,
        routing: OrderLifecycleRouting | None = None,
        reconciler_factory: Callable[[], PlacementReconciler] | None = None,
    ) -> None:
        """Wire collaborators; each omitted collaborator is self-wired.

        The finalization context is built at CALL TIME from the current
        self.<collaborator> values (see the finalization property), not once
        in __init__, so post-construction test reassignment keeps working.
        """
        defaults = build_default_order_collaborators()
        self.utils = utils if utils is not None else defaults.utils
        self.capital_budget = (
            capital_budget if capital_budget is not None else defaults.capital_budget
        )
        self.delisting_protection = (
            delisting_protection
            if delisting_protection is not None
            else defaults.delisting_protection
        )
        self.exchange = exchange if exchange is not None else defaults.exchange
        self.monitoring = monitoring if monitoring is not None else defaults.monitoring
        self.placement_workflow = (
            placement_workflow
            if placement_workflow is not None
            else defaults.placement_workflow
        )
        self.placement_intents = self.placement_workflow.intents
        self.trades = trades if trades is not None else defaults.trades
        self.routing = routing
        if self.routing is None:
            self.routing = OrderLifecycleRouting(
                trades=self.trades,
                placement_intents=self.placement_intents,
            )
        self.reconciler_factory = reconciler_factory

    @property
    def finalization(self) -> DcaFinalizationContext:
        """Build the finalization context from the current collaborators."""
        return DcaFinalizationContext(
            trades=self.trades,
            monitoring=self.monitoring,
            placement_workflow=self.placement_workflow,
            exchange=self.exchange,
            utils=self.utils,
        )

    def _build_placement_reconciler(self) -> PlacementReconciler:
        """Build the accepted-buy recovery reconciler for the bybit branch."""
        if self.reconciler_factory is not None:
            return self.reconciler_factory()
        return self._build_default_placement_reconciler()

    def _build_default_placement_reconciler(self) -> PlacementReconciler:
        """Build a recovery reconciler without the accumulation seam."""
        recovery = PlacementRecoveryHandler(
            exchange=self.exchange,
            trades=self.trades,
            validate_buy=has_valid_buy_fill,
            validate_sell=is_sold_check_status,
            finalize_buy=lambda status, config, **kwargs: finalize_buy_order(
                status,
                config,
                dependencies=self.finalization,
                **kwargs,
            ),
            finalize_sell=lambda status, config, **kwargs: finalize_completed_sell(
                status,
                config,
                dependencies=self.finalization,
                **kwargs,
            ),
            build_limit_sell_payload=lambda trades, evidence: (
                build_tp_limit_sell_payload(
                    trades,
                    evidence,
                    dependencies=self.finalization,
                )
            ),
            persist_limit_fallback=lambda limit_status, config, operation_id: (
                persist_reconciled_limit_fallback(
                    limit_status,
                    config,
                    operation_id,
                    dependencies=self.finalization,
                )
            ),
        )
        return PlacementReconciler(
            self.exchange,
            recovery.resume,
            self.placement_intents,
            accumulation_recovery=None,
        )

    async def close(self) -> None:
        """Close exchange resources owned by this order service."""
        await self.exchange.close()

    async def reconcile_tp_limit_order(
        self,
        trades: dict[str, Any],
        config: dict[str, Any],
        *,
        expected_snapshot: LifecycleSnapshotIdentity | None = None,
    ) -> bool:
        """Close the trade if its proactive TP limit order filled."""
        symbol = str(trades.get("symbol") or "")
        if not trades.get("tp_limit_order_id") or not symbol:
            return False
        async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
            if not admitted:
                logging.info("Skipping proactive TP reconciliation during maintenance.")
                return False
            if not await self.routing.snapshot_is_current(
                expected_snapshot,
                symbol,
                config,
            ):
                return False
            return await self._reconcile_tp_limit_order(trades, config)

    async def _reconcile_tp_limit_order(
        self,
        trades: dict[str, Any],
        config: dict[str, Any],
    ) -> bool:
        """Reconcile one proactive TP limit order with the symbol prelocked."""
        symbol = str(trades.get("symbol") or "")
        if not trades.get("tp_limit_order_id") or not symbol:
            return False
        async with lifecycle_mutation_coordinator.prelocked(symbol):
            return await self._reconcile_tp_limit_order_locked(trades, config)

    async def _reconcile_tp_limit_order_locked(
        self,
        trades: dict[str, Any],
        config: dict[str, Any],
    ) -> bool:
        """Reconcile a persisted proactive TP limit order while holding sell lock."""
        order_id = str(trades.get("tp_limit_order_id") or "").strip()
        symbol = str(trades.get("symbol") or "").strip()
        if not order_id or not symbol:
            return False

        try:
            exchange_status = await self.exchange.fetch_spot_order(
                symbol,
                order_id,
                config,
            )
            if not exchange_status:
                return False
            if is_exchange_order_filled(exchange_status):
                payload = build_tp_limit_sell_payload(
                    trades,
                    exchange_status,
                    dependencies=self.finalization,
                )
                order_status = await self.exchange.build_spot_sell_order_status(
                    payload,
                    config,
                )
                if not order_status:
                    logging.error(
                        "Filled proactive TP limit order %s for %s could not be "
                        "normalized. Keeping metadata for retry.",
                        order_id,
                        symbol,
                    )
                    return False
                if not is_sold_check_status(order_status):
                    if is_partial_sell_status(order_status):
                        await handle_partial_sell_status(
                            order_status,
                            config,
                            dependencies=self.finalization,
                        )
                        await self.trades.clear_tp_limit_order(symbol)
                        logging.info(
                            "Processed partial proactive TP limit fill for %s from order %s.",
                            symbol,
                            order_id,
                        )
                        return True
                    logging.error(
                        "Filled proactive TP limit order %s for %s returned "
                        "unsupported status: %s",
                        order_id,
                        symbol,
                        order_status,
                    )
                    return False
                await finalize_completed_sell(
                    order_status,
                    config,
                    dependencies=self.finalization,
                )
                logging.info(
                    "Closed %s from proactive TP limit order %s.",
                    symbol,
                    order_id,
                )
                return True
            if is_exchange_order_inactive(exchange_status):
                await self.trades.clear_tp_limit_order(
                    symbol,
                    exchange_status=exchange_status,
                )
                logging.info(
                    "Cleared inactive proactive TP limit order %s for %s.",
                    order_id,
                    symbol,
                )
            return False
        finally:
            await self.exchange.close()

    async def _cancel_tp_limit_order_locked(
        self,
        symbol: str,
        config: dict[str, Any],
    ) -> bool:
        """Cancel an armed proactive TP limit order while holding sell lock."""
        open_trade_rows = await self.trades.get_open_trades_by_symbol(symbol)
        open_trade = open_trade_rows[0] if open_trade_rows else None
        order_id = str((open_trade or {}).get("tp_limit_order_id") or "").strip()
        if not order_id:
            return True

        trade_data = await self.trades.get_trades_for_orders(symbol)
        if trade_data and await self._reconcile_tp_limit_order_locked(
            trade_data, config
        ):
            return False

        open_trade_rows = await self.trades.get_open_trades_by_symbol(symbol)
        open_trade = open_trade_rows[0] if open_trade_rows else None
        order_id = str((open_trade or {}).get("tp_limit_order_id") or "").strip()
        if not order_id:
            return True

        cancel_order = {
            "symbol": symbol,
            "side": "sell",
            "ordertype": "limit",
            "operation_id": build_derived_operation_id(
                PlacementAction.CANCEL,
                config.get("exchange"),
                symbol,
                order_id,
            ),
        }
        placement = await self.placement_workflow.begin(
            cancel_order,
            config,
            action=PlacementAction.CANCEL,
            side="sell",
            order_type="limit",
            exchange_order_id=order_id,
        )
        if placement.completed:
            return True
        if not placement.claimed:
            logging.warning(
                "Skipping duplicate cancel for %s order %s: operation=%s state=%s.",
                symbol,
                order_id,
                placement.operation_id,
                placement.state,
            )
            return False
        try:
            try:
                exchange_status = await self.exchange.cancel_spot_order(
                    symbol,
                    order_id,
                    config,
                )
            except ExchangeSubmissionIndeterminate as exc:
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.INDETERMINATE,
                    reason_code="cancel_response_lost",
                    error_message=str(exc),
                )
                return False
            if exchange_status and is_exchange_order_filled(exchange_status):
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.FILLED,
                    exchange_order_id=order_id,
                    result=dict(exchange_status),
                )
                if trade_data:
                    payload = build_tp_limit_sell_payload(
                        trade_data,
                        exchange_status,
                        dependencies=self.finalization,
                    )
                    order_status = await self.exchange.build_spot_sell_order_status(
                        payload,
                        config,
                    )
                    if order_status and is_sold_check_status(order_status):
                        await finalize_completed_sell(
                            order_status,
                            config,
                            placement_operation_id=placement.operation_id,
                            dependencies=self.finalization,
                        )
                    elif order_status and is_partial_sell_status(order_status):
                        await handle_partial_sell_status(
                            order_status,
                            config,
                            placement_operation_id=placement.operation_id,
                            dependencies=self.finalization,
                        )
                recovered = await self.placement_intents.get(
                    str(placement.operation_id or "")
                )
                if (
                    recovered is None
                    or str(recovered.state) != PlacementIntentState.PERSISTED.value
                ):
                    await self.placement_intents.transition(
                        placement.operation_id,
                        PlacementIntentState.QUARANTINED,
                        reason_code="order_filled_before_cancel_recovery_failed",
                    )
                    return False
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.COMPLETED,
                )
                return False
            if exchange_status is None:
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.INDETERMINATE,
                    reason_code="cancel_not_confirmed",
                )
                logging.warning(
                    "Could not confirm proactive TP limit order %s for %s after "
                    "cancel request. Keeping metadata for retry.",
                    order_id,
                    symbol,
                )
                return False

            if is_exchange_order_inactive(exchange_status):
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.ACCEPTED,
                    exchange_order_id=order_id,
                    result=dict(exchange_status),
                )
                await self.trades.clear_tp_limit_order(
                    symbol,
                    placement_operation_id=placement.operation_id,
                    exchange_status=exchange_status,
                )
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.COMPLETED,
                )
                logging.info(
                    "Canceled proactive TP limit order %s for %s.",
                    order_id,
                    symbol,
                )
                return True

            logging.warning(
                "Could not confirm proactive TP limit order %s for %s was canceled. "
                "Keeping the trade unchanged.",
                order_id,
                symbol,
            )
            await self.placement_intents.transition(
                placement.operation_id,
                PlacementIntentState.INDETERMINATE,
                reason_code="cancel_status_still_open",
                result=dict(exchange_status),
            )
            return False
        finally:
            await self.exchange.close()

    async def cancel_tp_limit_order(
        self,
        symbol: str,
        config: dict[str, Any],
        *,
        expected_snapshot: LifecycleSnapshotIdentity | None = None,
    ) -> bool:
        """Cancel a persisted proactive TP limit order if one exists."""
        async with lifecycle_mutation_coordinator.mutation(symbol) as admitted:
            if not admitted:
                logging.info(
                    "Skipping proactive TP cancellation for %s during maintenance.",
                    symbol,
                )
                return False
            return await self.cancel_tp_limit_order_prelocked(
                symbol,
                config,
                expected_snapshot=expected_snapshot,
            )

    async def cancel_tp_limit_order_prelocked(
        self,
        symbol: str,
        config: dict[str, Any],
        *,
        expected_snapshot: LifecycleSnapshotIdentity | None = None,
    ) -> bool:
        """Cancel a proactive TP order while the caller owns the symbol lock."""
        lifecycle_mutation_coordinator.assert_prelocked(symbol)
        if not await self.routing.snapshot_is_current(
            expected_snapshot,
            symbol,
            config,
        ):
            return False
        return await self._cancel_tp_limit_order(symbol, config)

    async def _cancel_tp_limit_order(
        self,
        symbol: str,
        config: dict[str, Any],
    ) -> bool:
        """Cancel one proactive TP order with the symbol prelocked."""
        async with lifecycle_mutation_coordinator.prelocked(symbol):
            return await self._cancel_tp_limit_order_locked(symbol, config)

    async def arm_tp_limit_order(
        self,
        order: dict[str, Any],
        config: dict[str, Any],
    ) -> bool:
        """Place and persist a proactive TP limit sell order."""
        async with lifecycle_mutation_coordinator.mutation(
            str(order["symbol"])
        ) as admitted:
            if not admitted:
                logging.info(
                    "Skipping proactive TP limit order for %s during maintenance.",
                    order["symbol"],
                )
                return False
            return await self._arm_tp_limit_order(order, config)

    async def _arm_tp_limit_order(
        self,
        order: dict[str, Any],
        config: dict[str, Any],
    ) -> bool:
        """Arm one proactive TP order with the symbol prelocked."""
        symbol = str(order["symbol"])
        async with lifecycle_mutation_coordinator.prelocked(symbol):
            if await self.routing.reject_legacy_lifecycle(symbol, "take_profit_prearm"):
                return False
            if not await self.routing.order_snapshot_is_current(order, config):
                return False
            placement = await self.placement_workflow.begin(
                order,
                config,
                action=PlacementAction.LIMIT_SELL,
                side="sell",
                order_type="limit",
                requested_amount=float(order.get("total_amount") or 0.0),
            )
            if placement.completed:
                return True
            if not placement.claimed:
                logging.warning(
                    "Skipping duplicate proactive TP placement for %s: "
                    "operation=%s state=%s.",
                    symbol,
                    placement.operation_id,
                    placement.state,
                )
                return False
            try:
                try:
                    order_status = await self.placement_workflow.submit(
                        placement.operation_id,
                        symbol=symbol,
                        side="sell",
                        submit=lambda: self.exchange.place_spot_limit_sell(
                            order, config
                        ),
                    )
                except (ExchangePostSubmissionFailure, ExchangeSubmissionIndeterminate):
                    return False
                if not order_status or order_status.get("requires_market_fallback"):
                    await self.placement_intents.transition(
                        placement.operation_id,
                        PlacementIntentState.REJECTED,
                        reason_code=str(
                            (order_status or {}).get("fallback_reason")
                            or "limit_order_not_placed"
                        ),
                        result=dict(order_status) if order_status else None,
                    )
                    if (
                        order_status
                        and order_status.get("requires_market_fallback")
                        and order_status.get("fallback_reason") == "minimum_notional"
                    ):
                        partial_status = build_partial_status_from_fallback(
                            order_status,
                            default_symbol=symbol,
                        )
                        partial_status["unsellable"] = True
                        partial_status["unsellable_reason"] = "minimum_notional"
                        await handle_partial_sell_status(
                            partial_status,
                            config,
                            placement_operation_id=placement.operation_id,
                            dependencies=self.finalization,
                        )
                    logging.info(
                        "Proactive TP limit order for %s was not armed: %s",
                        symbol,
                        (order_status or {}).get("fallback_reason"),
                    )
                    return False

                order_id = str(order_status.get("id") or "").strip()
                if not order_id:
                    await self.placement_intents.transition(
                        placement.operation_id,
                        PlacementIntentState.ACCEPTED,
                        result=dict(order_status),
                    )
                    await self.placement_intents.transition(
                        placement.operation_id,
                        PlacementIntentState.QUARANTINED,
                        reason_code="limit_order_missing_id",
                    )
                    logging.error(
                        "Proactive TP limit order for %s returned no order id.",
                        symbol,
                    )
                    return False

                price = float(
                    order_status.get("price")
                    or order_status.get("limit_price")
                    or order.get("limit_price")
                    or 0.0
                )
                amount = float(
                    order_status.get("total_amount")
                    or order_status.get("amount")
                    or order.get("total_amount")
                    or 0.0
                )
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.ACCEPTED,
                    exchange_order_id=order_id,
                    result=dict(order_status),
                )
                if placement.operation_id:
                    persisted = await self.trades.set_tp_limit_order(
                        symbol,
                        order_id=order_id,
                        price=price,
                        amount=amount,
                        placement_operation_id=placement.operation_id,
                    )
                else:
                    persisted = await self.trades.set_tp_limit_order(
                        symbol,
                        order_id=order_id,
                        price=price,
                        amount=amount,
                    )
                if not persisted:
                    compensation_reason = await self._cancel_unpersisted_tp_limit_order(
                        symbol,
                        order_id,
                        config,
                        source_operation_id=placement.operation_id,
                    )
                    await self.placement_intents.transition(
                        placement.operation_id,
                        PlacementIntentState.QUARANTINED,
                        reason_code=compensation_reason,
                    )
                    return False

                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.COMPLETED,
                )
                logging.info(
                    "Armed proactive TP limit order for %s: id=%s amount=%s price=%s.",
                    symbol,
                    order_id,
                    amount,
                    price,
                )
                return True
            finally:
                await self.exchange.close()

    async def _cancel_unpersisted_tp_limit_order(
        self,
        symbol: str,
        order_id: str,
        config: dict[str, Any],
        *,
        source_operation_id: str | None,
    ) -> str:
        """Durably compensate a limit order whose local metadata was not saved."""
        cancel_order = {
            "symbol": symbol,
            "side": "sell",
            "ordertype": "limit",
            "operation_id": build_derived_operation_id(
                PlacementAction.CANCEL,
                config.get("exchange"),
                symbol,
                order_id,
            ),
            "source_operation_id": source_operation_id,
        }
        cancellation = await self.placement_workflow.begin(
            cancel_order,
            config,
            action=PlacementAction.CANCEL,
            side="sell",
            order_type="limit",
            exchange_order_id=order_id,
        )
        if cancellation.completed:
            return "limit_metadata_persistence_failed_compensated"
        if not cancellation.claimed:
            return "limit_persistence_and_cancel_pending"

        try:
            exchange_status = await self.exchange.cancel_spot_order(
                symbol,
                order_id,
                config,
            )
        except ExchangeSubmissionIndeterminate as exc:
            await self.placement_intents.transition(
                cancellation.operation_id,
                PlacementIntentState.INDETERMINATE,
                reason_code="cancel_response_lost",
                error_message=str(exc),
            )
            return "limit_persistence_and_cancel_uncertain"

        if exchange_status is None:
            await self.placement_intents.transition(
                cancellation.operation_id,
                PlacementIntentState.INDETERMINATE,
                reason_code="cancel_not_confirmed",
            )
            return "limit_persistence_and_cancel_uncertain"

        if not is_exchange_order_inactive(exchange_status):
            target_state = (
                PlacementIntentState.REJECTED
                if is_exchange_order_filled(exchange_status)
                else PlacementIntentState.INDETERMINATE
            )
            await self.placement_intents.transition(
                cancellation.operation_id,
                target_state,
                exchange_order_id=order_id,
                result=dict(exchange_status),
                reason_code=(
                    "order_filled_before_cancel"
                    if target_state == PlacementIntentState.REJECTED
                    else "cancel_status_still_open"
                ),
            )
            return (
                "limit_persistence_failed_order_filled"
                if target_state == PlacementIntentState.REJECTED
                else "limit_persistence_and_cancel_uncertain"
            )

        await self.placement_intents.transition(
            cancellation.operation_id,
            PlacementIntentState.ACCEPTED,
            exchange_order_id=order_id,
            result=dict(exchange_status),
        )
        await self.placement_intents.transition(
            cancellation.operation_id,
            PlacementIntentState.PERSISTED,
        )
        await self.placement_intents.transition(
            cancellation.operation_id,
            PlacementIntentState.COMPLETED,
        )
        return "limit_metadata_persistence_failed_compensated"

    async def receive_sell_order(
        self, order: SellIntent | dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Create a sell order and persist closed trades."""
        async with lifecycle_mutation_coordinator.mutation(
            str(order["symbol"])
        ) as admitted:
            if not admitted:
                logging.info(
                    "Skipping sell order for %s during maintenance.",
                    order["symbol"],
                )
                return False
            return await self._receive_sell_order(order, config)

    async def _create_durable_market_fallback(
        self,
        remaining_order: dict[str, Any],
        config: dict[str, Any],
        limit_status: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Delegate fallback to the durable parent/child state machine."""
        return await DurableSellFallback(
            exchange=self.exchange,
            workflow=self.placement_workflow,
            persist_limit_fallback=lambda limit_status, config, operation_id: (
                persist_reconciled_limit_fallback(
                    limit_status,
                    config,
                    operation_id,
                    dependencies=self.finalization,
                )
            ),
            logger=logging,
        ).execute(remaining_order, config, limit_status)

    async def _receive_sell_order(
        self, order: SellIntent | dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Execute one sell order with the symbol prelocked."""
        logging.info("Incoming sell order for %s", order["symbol"])
        async with lifecycle_mutation_coordinator.prelocked(order["symbol"]):
            try:
                if await self.routing.reject_legacy_lifecycle(order["symbol"], "sell"):
                    return False
                if not await self.routing.order_snapshot_is_current(order, config):
                    return False
                if not bool(order.get("skip_tp_limit_cancel", False)):
                    canceled = await self._cancel_tp_limit_order_locked(
                        order["symbol"],
                        config,
                    )
                    if not canceled:
                        logging.warning(
                            "Skipping sell for %s because an armed proactive TP "
                            "limit order could not be canceled first.",
                            order["symbol"],
                        )
                        return False

                order["total_amount"] = await self.trades.get_token_amount_from_trades(
                    order["symbol"]
                )
                order["requested_total_amount"] = float(order["total_amount"] or 0.0)
                sell_order_type = str(config.get("sell_order_type") or "market").lower()

                placement = await self.placement_workflow.begin(
                    order,
                    config,
                    action=(
                        PlacementAction.LIMIT_SELL
                        if sell_order_type == "limit"
                        else PlacementAction.SELL
                    ),
                    side="sell",
                    order_type=sell_order_type,
                    requested_amount=float(order["requested_total_amount"]),
                )
                if placement.completed:
                    return True
                if not placement.claimed:
                    logging.warning(
                        "Skipping duplicate sell submission for %s: operation=%s "
                        "state=%s.",
                        order.get("symbol"),
                        placement.operation_id,
                        placement.state,
                    )
                    return False
                try:

                    async def submit_sell() -> dict[str, Any] | None:
                        if sell_order_type == "limit":
                            return await self.exchange.create_spot_sell(
                                order,
                                config,
                                create_market_fallback=self._create_durable_market_fallback,
                            )
                        return await self.exchange.create_spot_sell(order, config)

                    order_status = await self.placement_workflow.submit(
                        placement.operation_id,
                        symbol=order["symbol"],
                        side="sell",
                        submit=submit_sell,
                    )
                except (ExchangePostSubmissionFailure, ExchangeSubmissionIndeterminate):
                    return False

                if not order_status:
                    latest_placement = await self.placement_intents.get(
                        str(placement.operation_id or "")
                    )
                    if latest_placement is not None and is_terminal_placement_state(
                        latest_placement.state
                    ):
                        return (
                            latest_placement.state
                            == PlacementIntentState.COMPLETED.value
                        )
                    await self.placement_intents.transition(
                        placement.operation_id,
                        PlacementIntentState.REJECTED,
                        reason_code="exchange_rejected_or_unfilled",
                    )
                    logging.error(
                        "Failed creating sell order for %s. "
                        "No exchange sell result was returned.",
                        order["symbol"],
                    )
                    return False

                active_operation_id = str(
                    order_status.get("_placement_operation_id")
                    or placement.operation_id
                    or ""
                )
                source_operation_id = str(
                    order_status.get("_placement_source_operation_id") or ""
                )
                persistence_operation_ids = [
                    operation_id
                    for operation_id in (
                        active_operation_id,
                        source_operation_id,
                    )
                    if operation_id
                ]

                for key in (
                    "strategy_name",
                    "strategy_slug",
                    "strategy_version",
                    "timeframe",
                ):
                    if order_status.get(key) is None and order.get(key) is not None:
                        order_status[key] = order[key]

                if is_partial_sell_status(order_status):
                    if (
                        order_status.get("close_reason") is None
                        and order.get("sell_reason") is not None
                    ):
                        order_status["close_reason"] = str(order["sell_reason"])
                    partial_amount = float(
                        order_status.get("partial_filled_amount") or 0.0
                    )
                    if partial_amount <= 0:
                        await self.placement_intents.transition(
                            active_operation_id,
                            PlacementIntentState.REJECTED,
                            result=dict(order_status),
                            reason_code=str(
                                order_status.get("unsellable_reason")
                                or order_status.get("fallback_reason")
                                or "no_sell_fill"
                            ),
                        )
                        await handle_partial_sell_status(
                            order_status,
                            config,
                            dependencies=self.finalization,
                        )
                        return False
                    await self.placement_intents.transition(
                        active_operation_id,
                        PlacementIntentState.FILLED,
                        exchange_order_id=str(order_status.get("id") or "") or None,
                        result=dict(order_status),
                    )
                    if source_operation_id:
                        await handle_partial_sell_status(
                            order_status,
                            config,
                            placement_operation_ids=persistence_operation_ids,
                            dependencies=self.finalization,
                        )
                    else:
                        await handle_partial_sell_status(
                            order_status,
                            config,
                            placement_operation_id=active_operation_id,
                            dependencies=self.finalization,
                        )
                    for operation_id in persistence_operation_ids:
                        await self.placement_intents.transition(
                            operation_id,
                            PlacementIntentState.COMPLETED,
                        )
                    return True

                if not is_sold_check_status(order_status):
                    await self.placement_intents.transition(
                        active_operation_id,
                        PlacementIntentState.ACCEPTED,
                        exchange_order_id=str(order_status.get("id") or "") or None,
                        result=dict(order_status),
                    )
                    await self.placement_intents.transition(
                        active_operation_id,
                        PlacementIntentState.QUARANTINED,
                        reason_code="unsupported_sell_result",
                    )
                    logging.error(
                        "Unsupported sell order status for %s: %s",
                        order["symbol"],
                        order_status,
                    )
                    return False

                if (
                    order_status.get("close_reason") is None
                    and order.get("sell_reason") is not None
                ):
                    order_status["close_reason"] = order["sell_reason"]

                await self.placement_intents.transition(
                    active_operation_id,
                    PlacementIntentState.FILLED,
                    exchange_order_id=str(
                        order_status.get("id") or order_status.get("orderid") or ""
                    )
                    or None,
                    result=dict(order_status),
                )
                if source_operation_id:
                    await finalize_completed_sell(
                        order_status,
                        config,
                        placement_operation_ids=persistence_operation_ids,
                        dependencies=self.finalization,
                    )
                else:
                    await finalize_completed_sell(
                        order_status,
                        config,
                        placement_operation_id=active_operation_id,
                        dependencies=self.finalization,
                    )
                for operation_id in persistence_operation_ids:
                    await self.placement_intents.transition(
                        operation_id,
                        PlacementIntentState.COMPLETED,
                    )
                return True
            finally:
                await self.exchange.close()

    async def receive_buy_order(
        self, order: BuyIntent | dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Create a buy order and persist open trades."""
        async with lifecycle_mutation_coordinator.mutation(
            str(order["symbol"])
        ) as admitted:
            if not admitted:
                logging.info(
                    "Skipping buy order for %s during maintenance.",
                    order["symbol"],
                )
                return False
            return await self.receive_buy_order_prelocked(order, config)

    async def receive_buy_order_prelocked(
        self,
        order: BuyIntent | dict[str, Any],
        config: dict[str, Any],
    ) -> bool:
        """Execute a buy while the caller owns the symbol lifecycle lock."""
        lifecycle_mutation_coordinator.assert_prelocked(str(order["symbol"]))
        return await self._receive_buy_order(order, config)

    async def _receive_buy_order(
        self, order: BuyIntent | dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Execute one buy order with the symbol prelocked."""
        lifecycle_mutation_coordinator.assert_prelocked(str(order["symbol"]))
        logging.info("Incoming buy order for %s", order["symbol"])
        if not await self.routing.order_snapshot_is_current(order, config):
            return False
        if await self.routing.reject_legacy_lifecycle(order["symbol"], "buy"):
            return False

        try:
            existing_trade = await self.trades.get_trades_for_orders(order["symbol"])
        except (RuntimeError, ConfigurationError):
            # Isolated tests may exercise order orchestration without a live DB
            # context; runtime paths still resolve the full mission snapshot.
            existing_trade = None
        gate = evaluate_buy_like_gate(
            symbol=str(order.get("symbol") or ""),
            config=config,
            trade_data=existing_trade,
        )
        if not gate.allowed:
            logging.warning(
                "Skipping buy order for %s: %s (%s).",
                order["symbol"],
                gate.reason_code,
                gate.message,
            )
            return False

        delisting_decision = await self.delisting_protection.evaluate_buy(
            str(order.get("symbol") or ""),
            config,
        )
        if not delisting_decision.allowed:
            order_role = (
                "safety_order"
                if bool(order.get("safetyorder")) and not bool(order.get("baseorder"))
                else "base_or_reentry"
            )
            logging.warning(
                "Skipping %s buy for %s: %s (%s). source=%s delist_at=%s",
                order_role,
                order["symbol"],
                delisting_decision.reason_code,
                delisting_decision.message,
                delisting_decision.source,
                delisting_decision.delist_at,
            )
            return False

        ai_gate = await evaluate_entry_enforcement(
            str(order.get("symbol") or ""),
            order,
            config,
        )
        if not ai_gate.allowed:
            if ai_gate.reason_code == "ai_trust_unavailable":
                logging.warning(
                    "Skipping entry order for %s: AI trust enforcement requires "
                    "a scored response but provider_status=%s.",
                    order["symbol"],
                    ai_gate.provider_status,
                )
            else:
                logging.warning(
                    "Skipping entry order for %s: AI trust warning enforcement "
                    "blocked the entry (risk=%s severity=%s note=%s).",
                    order["symbol"],
                    ai_gate.risk_score,
                    ai_gate.warning_severity,
                    ai_gate.operator_note,
                )
            return False
        order["_ai_entry_evaluation"] = ai_gate

        try:
            if bool(order.get("safetyorder")) and not bool(order.get("baseorder")):
                canceled = await self._cancel_tp_limit_order_locked(
                    order["symbol"],
                    config,
                )
                if not canceled:
                    logging.warning(
                        "Skipping safety order for %s because an armed proactive "
                        "TP limit order could not be canceled first.",
                        order["symbol"],
                    )
                    return False

            order_filled, precheck = await self._execute_budgeted_buy_order(
                dict(order),
                config,
            )
            if order_filled:
                return True
            retry_order = build_entry_size_retry_order(order, precheck)
            if retry_order is not None:
                logging.warning(
                    "Retrying buy order for %s with baseline base order %s after entry sizing fallback (%s).",
                    order["symbol"],
                    retry_order["ordersize"],
                    (precheck or {}).get("reason", "unknown"),
                )
                retry_filled, precheck = await self._execute_budgeted_buy_order(
                    dict(retry_order),
                    config,
                )
                if retry_filled:
                    return True

            log_buy_failure(order["symbol"], precheck)
            return False
        finally:
            await self.exchange.close()

    async def _execute_budgeted_buy_order(
        self,
        order: dict[str, Any],
        config: dict[str, Any],
    ) -> tuple[bool, dict[str, Any] | None]:
        """Run capital-budget preflight, exchange buy, and persistence."""
        if config.get("exchange") in {
            "bybit",
            "bybiteu",
        } and is_exchange_placement_enabled(config):
            for pending in await self.placement_intents.list_nonterminal():
                if (
                    str(pending.exchange_name) == config.get("exchange")
                    and str(pending.symbol) == str(order.get("symbol") or "")
                    and str(pending.action) == PlacementAction.BUY.value
                    and str(pending.state)
                    in {
                        PlacementIntentState.ACCEPTED.value,
                        PlacementIntentState.RECONCILING.value,
                        PlacementIntentState.FILLED.value,
                        PlacementIntentState.PERSISTED.value,
                    }
                ):
                    outcome = (
                        await self._build_placement_reconciler().reconcile_operation(
                            str(pending.operation_id), config
                        )
                    )
                    return outcome == PlacementIntentState.COMPLETED.value, (
                        None
                        if outcome == PlacementIntentState.COMPLETED.value
                        else {
                            "ok": False,
                            "reason": f"placement_{outcome}",
                            "symbol": str(order.get("symbol") or ""),
                        }
                    )
        budget_lease, budget_check = await self.capital_budget.acquire_order_lease(
            order,
            config,
        )
        if not budget_check.ok:
            precheck = budget_check.to_precheck_result()
            logging.warning(
                "Skipping buy for %s: capital budget check failed (%s). required=%s available=%s",
                order.get("symbol"),
                precheck.get("reason", "unknown"),
                precheck.get("required_quote"),
                precheck.get("available_quote"),
            )
            return False, precheck

        order_type = (
            "limit"
            if float(order.get("maximum_buy_price") or 0.0) > 0
            else str(order.get("ordertype") or "market")
        )
        placement = await self.placement_workflow.begin(
            order,
            config,
            action=PlacementAction.BUY,
            side="buy",
            order_type=order_type,
            requested_quote=float(budget_check.order_quote or 0.0),
            reserved_quote=float(budget_check.required_quote or 0.0),
        )
        await budget_lease.bind_operation(placement.operation_id)
        try:
            if placement.completed:
                return True, None
            if not placement.claimed:
                if (
                    placement.state == PlacementIntentState.ACCEPTED.value
                    and placement.operation_id
                    and config.get("exchange") in {"bybit", "bybiteu"}
                ):
                    outcome = (
                        await self._build_placement_reconciler().reconcile_operation(
                            placement.operation_id, config
                        )
                    )
                    if outcome == PlacementIntentState.COMPLETED.value:
                        return True, None
                    return False, {
                        "ok": False,
                        "reason": f"placement_{outcome}",
                        "symbol": str(order.get("symbol") or ""),
                    }
                logging.warning(
                    "Skipping duplicate buy submission for %s: operation=%s state=%s.",
                    order.get("symbol"),
                    placement.operation_id,
                    placement.state,
                )
                return (
                    False,
                    {
                        "ok": False,
                        "reason": f"placement_{placement.state}",
                        "symbol": str(order.get("symbol") or ""),
                    },
                )

            try:
                order_status = await self.placement_workflow.submit(
                    placement.operation_id,
                    symbol=order["symbol"],
                    side="buy",
                    submit=lambda: self.exchange.create_spot_market_buy(order, config),
                )
            except ExchangePostSubmissionFailure:
                return False, {
                    "ok": False,
                    "reason": "placement_reconciliation_pending",
                    "symbol": str(order.get("symbol") or ""),
                }
            except ExchangeSubmissionIndeterminate:
                return False, {
                    "ok": False,
                    "reason": "placement_indeterminate",
                    "symbol": str(order.get("symbol") or ""),
                }
            if not order_status:
                precheck = self.exchange.get_last_buy_precheck_result()
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.REJECTED,
                    reason_code=str((precheck or {}).get("reason") or "not_filled"),
                )
                return False, precheck
            if not has_valid_buy_fill(order_status):
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.ACCEPTED,
                    exchange_order_id=str(order_status.get("id") or "") or None,
                    result=dict(order_status),
                )
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.QUARANTINED,
                    reason_code="invalid_buy_fill",
                    error_message="Exchange returned an accepted buy without a valid fill.",
                )
                return (
                    False,
                    {
                        "ok": False,
                        "reason": "placement_quarantined",
                        "symbol": str(order.get("symbol") or ""),
                    },
                )
            await self.placement_intents.transition(
                placement.operation_id,
                PlacementIntentState.FILLED,
                exchange_order_id=str(
                    order_status.get("id") or order_status.get("orderid") or ""
                )
                or None,
                result=dict(order_status),
            )
            finalized = await finalize_buy_order(
                order_status,
                config,
                original_order=order,
                placement_operation_id=placement.operation_id,
                dependencies=self.finalization,
            )
            if not finalized:
                return False, None
            await self.placement_intents.transition(
                placement.operation_id,
                PlacementIntentState.COMPLETED,
            )
            return True, None
        finally:
            await budget_lease.release()

    async def receive_manual_buy_add(
        self,
        symbol: str,
        date_input: Any,
        price_raw: Any,
        amount_raw: Any,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Append a manual buy as a safety-order row without exchange execution."""
        normalized_symbol = normalize_order_symbol(symbol)
        async with lifecycle_mutation_coordinator.mutation(
            normalized_symbol
        ) as admitted:
            if not admitted:
                raise ValueError("Cannot add a manual buy during backup restore.")
            return await self._receive_manual_buy_add(
                normalized_symbol,
                date_input,
                price_raw,
                amount_raw,
                config,
            )

    async def _receive_manual_buy_add(
        self,
        symbol: str,
        date_input: Any,
        price_raw: Any,
        amount_raw: Any,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one manual buy with the symbol prelocked."""
        request = parse_manual_buy_add_request(
            symbol=symbol,
            date_input=date_input,
            price_raw=price_raw,
            amount_raw=amount_raw,
        )
        normalized_symbol = request.symbol
        lifecycle_mutation_coordinator.assert_prelocked(normalized_symbol)

        rejection = await self.routing.reject_legacy_lifecycle(
            normalized_symbol, "manual_buy_add"
        )
        if rejection is not None:
            raise ValueError(rejection.user_message)

        open_trade_rows = await self.trades.get_open_trades_by_symbol(normalized_symbol)
        if not open_trade_rows:
            raise ValueError(f"No open trade found for {normalized_symbol}.")
        open_trade = open_trade_rows[0]

        existing_trades = await self.trades.get_trades_by_symbol(normalized_symbol)
        if not existing_trades:
            raise ValueError(f"No existing trade rows found for {normalized_symbol}.")

        last_trade = max(
            existing_trades,
            key=lambda trade: float(trade.get("timestamp") or 0.0),
        )
        last_timestamp = int(float(last_trade.get("timestamp") or 0.0))
        if request.timestamp_ms < last_timestamp:
            raise ValueError(
                "Date must be greater than or equal to the latest existing buy date."
            )

        trade_data = await self.trades.get_trades_for_orders(normalized_symbol)
        if not trade_data:
            raise ValueError(f"Cannot resolve trade context for {normalized_symbol}.")
        gate = evaluate_buy_like_gate(
            symbol=normalized_symbol,
            config=config,
            trade_data=trade_data,
        )
        if not gate.allowed:
            raise ValueError(gate.message or "Manual buy add is currently blocked.")

        previous_price = float(last_trade.get("price") or 0.0)
        ordersize = calculate_order_size(price=request.price, amount=request.amount)
        so_percentage = calculate_so_percentage(
            price=request.price,
            previous_price=previous_price,
            is_base=False,
        )
        safetyorders_count = int(trade_data.get("safetyorders_count") or 0)
        order_count = safetyorders_count + 1

        trade_payload = build_manual_buy_trade_payload(
            normalized_symbol=normalized_symbol,
            timestamp_ms=request.timestamp_ms,
            price=request.price,
            amount=request.amount,
            ordersize=float(ordersize),
            amount_precision=request.amount_precision,
            order_count=order_count,
            so_percentage=so_percentage,
            trade_data=trade_data,
        )
        open_trade_payload = build_manual_buy_open_trade_payload(
            open_trade=open_trade,
            amount=request.amount,
            ordersize=float(ordersize),
            order_count=order_count,
            tp_percent=float(config.get("tp", 0.0) or 0.0),
        )
        budget_warning = await self._build_manual_buy_budget_warning(
            normalized_symbol,
            float(ordersize),
            order_count,
            config,
        )

        canceled = await self._cancel_tp_limit_order_locked(
            normalized_symbol,
            config,
        )
        if not canceled:
            raise ValueError(
                "Cannot add manual buy while the proactive TP limit order is filled "
                "or could not be canceled."
            )

        await persist_manual_buy_add(
            normalized_symbol,
            trade_payload,
            open_trade_payload,
        )
        await self.trades.invalidate_trade_caches()
        return {
            "symbol": normalized_symbol,
            "timestamp": request.timestamp_ms,
            "price": request.price,
            "amount": request.amount,
            "ordersize": float(ordersize),
            "so_percentage": float(so_percentage),
            "order_count": order_count,
            **({"capital_budget_warning": budget_warning} if budget_warning else {}),
        }

    async def _build_manual_buy_budget_warning(
        self,
        symbol: str,
        ordersize: float,
        order_count: int,
        config: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Return a warning payload for ledger-only manual buys that exceed budget."""
        budget_check = await self.capital_budget.check_order(
            {
                "ordersize": float(ordersize),
                "symbol": symbol,
                "baseorder": False,
                "safetyorder": True,
                "order_count": order_count,
            },
            config,
        )
        if budget_check.ok:
            return None
        warning = budget_check.to_precheck_result()
        logging.warning(
            "Manual ledger buy add for %s exceeds capital budget (%s). "
            "Recording ledger row without exchange execution.",
            symbol,
            warning.get("reason", "unknown"),
        )
        return warning

    async def receive_stop_signal(
        self,
        symbol: str,
        config: dict[str, Any] | None = None,
        *,
        expected_snapshot: LifecycleSnapshotIdentity | None = None,
    ) -> bool:
        """Stop trading for a symbol."""
        try:
            normalized_symbol = normalize_order_symbol(symbol)
            async with lifecycle_mutation_coordinator.mutation(
                normalized_symbol
            ) as admitted:
                if not admitted:
                    logging.info(
                        "Skipping stop order for %s during maintenance.",
                        normalized_symbol,
                    )
                    return False
                if not await self.routing.snapshot_is_current(
                    expected_snapshot,
                    normalized_symbol,
                    config or {},
                ):
                    return False
                return await self._receive_stop_signal(normalized_symbol, config)
        except ValueError:
            logging.warning("Skipping stop order with invalid symbol: %s", symbol)
            return False

    async def receive_stop_signal_result(
        self,
        symbol: str,
        config: dict[str, Any],
        *,
        operation_id: str | None = None,
    ) -> OrderMutationResult:
        """Stop a trade and return an explicit operator-visible outcome."""
        try:
            normalized_symbol = normalize_order_symbol(symbol)
        except ValueError:
            return OrderMutationResult(
                operation_id=str(operation_id or ""),
                symbol=str(symbol or ""),
                action="manual_stop",
                status=OrderMutationStatus.REJECTED,
                reason_code="invalid_symbol",
                user_message="The symbol is invalid.",
            )
        rejection = await self.routing.reject_legacy_lifecycle(
            normalized_symbol, "manual_stop", operation_id
        )
        if rejection is not None:
            return rejection
        try:
            trade = await self.routing.load_authoritative_trade(normalized_symbol)
        except TradeStateUnavailableError:
            return self.routing.trade_state_unavailable_result(
                operation_id=operation_id,
                symbol=normalized_symbol,
                action="manual_stop",
            )
        if trade is None:
            return OrderMutationResult(
                operation_id=str(operation_id or ""),
                symbol=normalized_symbol,
                action="manual_stop",
                status=OrderMutationStatus.REJECTED,
                reason_code="trade_not_found",
                user_message="No active trade was found.",
            )
        snapshot = LifecycleSnapshotIdentity.from_trade(trade, config)
        resolved_operation_id = str(
            operation_id
            or build_derived_operation_id(
                "manual_stop",
                snapshot.deal_id,
                snapshot.execution_count,
            )
        )
        applied = await self.receive_stop_signal(
            normalized_symbol,
            config,
            expected_snapshot=snapshot,
        )
        if applied:
            status = OrderMutationStatus.APPLIED
            reason_code = "mutation_applied"
            message = "The trade was stopped."
        else:
            current_trade = await self.routing.load_fresh_trade(normalized_symbol)
            is_stale = current_trade is not None and not snapshots_match(
                snapshot,
                current_trade,
                config,
            )
            status = (
                OrderMutationStatus.STALE if is_stale else OrderMutationStatus.REJECTED
            )
            reason_code = "stale_snapshot" if is_stale else "mutation_rejected"
            message = (
                "Trade state changed before execution. Refresh and try again."
                if is_stale
                else "The trade could not be stopped."
            )
        return OrderMutationResult(
            operation_id=resolved_operation_id,
            symbol=normalized_symbol,
            action="manual_stop",
            status=status,
            reason_code=reason_code,
            user_message=message,
        )

    async def _receive_stop_signal(
        self,
        symbol: str,
        config: dict[str, Any] | None = None,
    ) -> bool:
        """Close the ledger at its current market mark without selling inventory."""
        logging.info("Incoming stop order")
        symbol = normalize_order_symbol(symbol)
        lifecycle_mutation_coordinator.assert_prelocked(symbol)
        if await self.routing.reject_legacy_lifecycle(symbol, "manual_stop"):
            return False
        try:
            canceled = await self._cancel_tp_limit_order_locked(
                symbol,
                config or {},
            )
            if not canceled:
                return False
            # Cancellation can record another partial fill. Reload under the
            # lifecycle lock so only the remaining coins receive the market mark.
            trade = await self.routing.load_authoritative_trade(symbol)
            if trade is None:
                return False
            price = float(trade.get("current_price") or 0.0)
            amount = float(trade["sellable_amount"])
            cost = float(trade["total_cost"])
            if (
                not all(math.isfinite(value) for value in (price, amount, cost))
                or price <= 0
                or amount < 0
                or cost <= 0
            ):
                logging.warning("Cannot value stopped trade for %s.", symbol)
                return False
            # A stop must trust the already-sold proceeds: read them fail-closed
            # so a transient error aborts the close instead of committing wrong
            # P&L on silently swallowed zero totals (the persist reuses a retrying
            # write, so a read failure must not be tolerated here).
            (
                partial_amount,
                partial_proceeds,
            ) = await self.trades.get_partial_sell_execution(symbol, fail_on_error=True)
            close_context = await calculate_closed_trade_stats(
                {
                    "symbol": symbol,
                    "total_cost": cost,
                    "total_amount": amount,
                    "price": price,
                    "close_reason": "manual_stop",
                    "metadata_json": json.dumps(
                        {"valuation_only": True, "source": "manual_stop"}
                    ),
                },
                dependencies=self.finalization,
                partial_amount=partial_amount,
                partial_proceeds=partial_proceeds,
            )
            payload = close_context["payload"]
            payload["valuation_quantity"] = amount
            payload["valuation_price"] = price
            payload["sell_executions"] = []
            # Existing partial-sale totals are gross and do not prove fee coverage.
            payload["profit"] = None
            payload["profit_percent"] = None
            payload["tp_price"] = (
                partial_proceeds / partial_amount if partial_amount > 0 else None
            )
            await persist_closed_trade(symbol, close_context["payload"])
            await self.trades.invalidate_trade_caches()
            return True
        except (
            BaseORMException,
            RuntimeError,
            TypeError,
            ValueError,
            OSError,
            sqlite3.Error,
        ) as e:
            logging.error(
                "Cannot stop trade for %s. See trade logs for errors. Cause: %s",
                symbol,
                e,
                exc_info=True,
            )
            return False

    async def receive_sell_signal(self, symbol: str, config: dict[str, Any]) -> bool:
        """Handle a manual sell signal."""
        symbol = normalize_order_symbol(symbol)
        if await self.routing.reject_legacy_lifecycle(symbol, "manual_sell"):
            return False
        trades = await self.trades.get_trades_for_orders(symbol)
        if not trades:
            logging.error("No running trade found for manual sell of %s.", symbol)
            return False

        actual_pnl = self.utils.calculate_actual_pnl(trades)
        order = build_manual_sell_order_intent(trades, actual_pnl)
        return await self.receive_sell_order(order, config)

    async def receive_sell_signal_result(
        self,
        symbol: str,
        config: dict[str, Any],
        *,
        operation_id: str | None = None,
    ) -> OrderMutationResult:
        """Handle a manual sell and report its durable execution outcome."""
        symbol = normalize_order_symbol(symbol)
        rejection = await self.routing.reject_legacy_lifecycle(
            symbol, "manual_sell", operation_id
        )
        if rejection is not None:
            return rejection
        try:
            trades = await self.routing.load_authoritative_trade(symbol)
        except TradeStateUnavailableError:
            return self.routing.trade_state_unavailable_result(
                operation_id=operation_id,
                symbol=symbol,
                action="manual_sell",
            )
        if not trades:
            if operation_id:
                existing = await self.routing.get_placement_intent(str(operation_id))
                if existing is not None:
                    status = (
                        OrderMutationStatus.DEDUPLICATED
                        if str(existing.state) == PlacementIntentState.COMPLETED.value
                        else OrderMutationStatus.INDETERMINATE
                    )
                    return OrderMutationResult(
                        operation_id=str(operation_id),
                        symbol=symbol,
                        action="manual_sell",
                        status=status,
                        reason_code=(
                            "duplicate_operation"
                            if status is OrderMutationStatus.DEDUPLICATED
                            else str(existing.reason_code or existing.state)
                        ),
                        user_message=(
                            "This operation was already completed; no duplicate "
                            "order was sent."
                            if status is OrderMutationStatus.DEDUPLICATED
                            else "The exchange outcome is not yet known. "
                            "Reconciliation is required."
                        ),
                        exchange_order_id=str(existing.exchange_order_id or "") or None,
                        client_order_id=str(existing.client_order_id or "") or None,
                    )
            logging.error("No running trade found for manual sell of %s.", symbol)
            return OrderMutationResult(
                operation_id=str(operation_id or ""),
                symbol=symbol,
                action="manual_sell",
                status=OrderMutationStatus.REJECTED,
                reason_code="trade_not_found",
                user_message="No active trade was found.",
            )

        snapshot = LifecycleSnapshotIdentity.from_trade(trades, config)
        actual_pnl = self.utils.calculate_actual_pnl(trades)
        order = build_manual_sell_order_intent(trades, actual_pnl)
        order["lifecycle_snapshot"] = snapshot.to_dict()
        if operation_id:
            order["operation_id"] = str(operation_id)
        else:
            ensure_operation_id(order, "manual_sell")
        preexisting = await self.routing.get_placement_intent(order["operation_id"])
        applied = await self.receive_sell_order(order, config)
        return await self.routing.operator_mutation_result(
            order=order,
            action="manual_sell",
            applied=applied,
            preexisting_operation=preexisting is not None,
            expected_snapshot=snapshot,
            config=config,
        )

    async def receive_buy_signal(
        self, symbol: str, ordersize: float, config: dict[str, Any]
    ) -> bool:
        """Handle a manual buy signal."""
        symbol = normalize_order_symbol(symbol)
        if await self.routing.reject_legacy_lifecycle(symbol, "manual_buy"):
            return False
        trades = await self.trades.get_trades_for_orders(symbol)

        if not trades:
            return False

        actual_pnl = self.utils.calculate_actual_pnl(trades)
        order = build_manual_buy_order_intent(symbol, ordersize, trades, actual_pnl)
        return await self.receive_buy_order(order, config)

    async def receive_buy_signal_result(
        self,
        symbol: str,
        ordersize: float,
        config: dict[str, Any],
        *,
        operation_id: str | None = None,
    ) -> OrderMutationResult:
        """Handle a manual safety buy and report its durable outcome."""
        symbol = normalize_order_symbol(symbol)
        rejection = await self.routing.reject_legacy_lifecycle(
            symbol, "manual_buy", operation_id
        )
        if rejection is not None:
            return rejection
        if operation_id:
            existing = await self.routing.get_placement_intent(str(operation_id))
            if existing is not None:
                return self.routing.operator_result_from_intent(
                    intent=existing,
                    operation_id=str(operation_id),
                    symbol=symbol,
                    action="manual_buy",
                    applied=False,
                    preexisting_operation=True,
                )
        try:
            trades = await self.routing.load_authoritative_trade(symbol)
        except TradeStateUnavailableError:
            return self.routing.trade_state_unavailable_result(
                operation_id=operation_id,
                symbol=symbol,
                action="manual_buy",
            )

        if not trades:
            return OrderMutationResult(
                operation_id=str(operation_id or ""),
                symbol=symbol,
                action="manual_buy",
                status=OrderMutationStatus.REJECTED,
                reason_code="trade_not_found",
                user_message="No active trade was found.",
            )

        snapshot = LifecycleSnapshotIdentity.from_trade(trades, config)
        actual_pnl = self.utils.calculate_actual_pnl(trades)
        order = build_manual_buy_order_intent(symbol, ordersize, trades, actual_pnl)
        order["lifecycle_snapshot"] = snapshot.to_dict()
        if operation_id:
            order["operation_id"] = str(operation_id)
        else:
            ensure_operation_id(order, "manual_buy")
        preexisting = await self.routing.get_placement_intent(order["operation_id"])
        applied = await self.receive_buy_order(order, config)
        return await self.routing.operator_mutation_result(
            order=order,
            action="manual_buy",
            applied=applied,
            preexisting_operation=preexisting is not None,
            expected_snapshot=snapshot,
            config=config,
        )
