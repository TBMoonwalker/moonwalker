"""Order orchestration for exchange buy/sell actions."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, TypeGuard

import helper
from service.ai_trust import evaluate_entry_enforcement
from service.capital_budget import CapitalBudgetService
from service.dca_recovery_sizing import build_recovery_sizing_policy
from service.delisting_protection import DelistingProtectionService
from service.exchange import Exchange
from service.exchange_capabilities import (
    ExchangePostSubmissionFailure,
    ExchangeSubmissionIndeterminate,
)
from service.exchange_limit_sell import build_partial_status_from_fallback
from service.exchange_types import (
    ExchangeOrderPayload,
    PartialSellStatus,
    SoldCheckStatus,
)
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.lifecycle_snapshot import (
    LifecycleSnapshotIdentity,
    snapshots_match,
)
from service.monitoring import MonitoringService
from service.order_close_context import (
    build_unsellable_remainder_context,
    build_unsellable_status_snapshot,
)
from service.order_intents import (
    build_manual_buy_order_intent,
    build_manual_sell_order_intent,
)
from service.order_mutation_result import (
    OrderMutationResult,
    OrderMutationStatus,
)
from service.order_payloads import (
    build_buy_monitor_payload,
    build_buy_trade_payload,
    build_closed_trade_payloads,
    build_manual_buy_open_trade_payload,
    build_manual_buy_trade_payload,
    trade_datetime_from_ms,
)
from service.order_persistence import (
    persist_buy_trade,
    persist_closed_trade,
    persist_manual_buy_add,
    persist_partial_sell_execution,
    persist_sidestep_transition,
    persist_stopped_trade,
    persist_unsellable_remainder,
)
from service.order_requests import normalize_order_symbol, parse_manual_buy_add_request
from service.placement_intents import (
    PlacementAction,
    PlacementIntentState,
    build_derived_operation_id,
    ensure_operation_id,
    is_terminal_placement_state,
)
from service.placement_reconciliation import (
    PlacementReconciler,
    PlacementReconciliationSummary,
)
from service.placement_recovery import PlacementRecoveryHandler
from service.placement_workflow import PlacementWorkflow
from service.sell_fallback_workflow import DurableSellFallback
from service.spot_campaign_types import TradeCloseReason
from service.spot_sidestep_campaign import SpotSidestepCampaignService
from service.trade_math import calculate_order_size, calculate_so_percentage
from service.trades import Trades, TradeStateUnavailableError
from service.trading_contracts import BuyIntent, SellIntent
from service.trading_controls import evaluate_buy_like_gate
from tortoise.exceptions import ConfigurationError

logging = helper.LoggerFactory.get_logger("logs/orders.log", "orders")


class Orders:
    """Handle incoming buy/sell signals and persist trades."""

    _ENTRY_SIZING_RETRY_REASONS = {
        "capital_budget_exceeded",
        "insufficient_quote_balance",
        "invalid_required_quote",
        "invalid_price_or_amount",
    }

    def __init__(self):
        self.utils = helper.Utils()
        self.capital_budget = CapitalBudgetService()
        self.delisting_protection = DelistingProtectionService.shared()
        self.exchange = Exchange()
        self.monitoring = MonitoringService()
        self.placement_workflow = PlacementWorkflow()
        self.placement_intents = self.placement_workflow.intents
        self.trades = Trades()
        self.sidestep_campaigns: SpotSidestepCampaignService | None = None

    async def close(self) -> None:
        """Close exchange resources owned by this order service."""
        await self.exchange.close()

    @staticmethod
    def _expected_lifecycle_snapshot(
        order: dict[str, Any],
    ) -> LifecycleSnapshotIdentity | None:
        """Parse an optional evaluated lifecycle identity from an order."""
        raw_snapshot = order.get("lifecycle_snapshot")
        if not isinstance(raw_snapshot, dict):
            return None
        try:
            return LifecycleSnapshotIdentity.from_dict(raw_snapshot)
        except (TypeError, ValueError):
            logging.warning(
                "Rejecting %s mutation with invalid lifecycle snapshot.",
                order.get("symbol"),
            )
            return None

    async def _load_fresh_trade(self, symbol: str) -> dict[str, Any] | None:
        """Reload authoritative trade state without the dashboard TTL cache."""
        fresh_loader = getattr(self.trades, "get_trades_for_orders_fresh", None)
        if callable(fresh_loader):
            return await fresh_loader(symbol)
        return await self.trades.get_trades_for_orders(symbol)

    async def _load_authoritative_trade(self, symbol: str) -> dict[str, Any] | None:
        """Load mutation state without converting database failures to absence."""
        authoritative_loader = getattr(
            self.trades,
            "get_trades_for_orders_authoritative",
            None,
        )
        if callable(authoritative_loader):
            return await authoritative_loader(symbol)
        return await self._load_fresh_trade(symbol)

    @staticmethod
    def _trade_state_unavailable_result(
        *,
        operation_id: str | None,
        symbol: str,
        action: str,
    ) -> OrderMutationResult:
        """Return a fail-closed operator result for an unreadable trade ledger."""
        return OrderMutationResult(
            operation_id=str(operation_id or ""),
            symbol=symbol,
            action=action,
            status=OrderMutationStatus.REJECTED,
            reason_code="trade_state_unavailable",
            user_message="Trade state could not be loaded. No order was sent.",
        )

    async def _get_placement_intent(self, operation_id: str) -> Any | None:
        """Read a durable intent when persistence is available."""
        try:
            return await self.placement_intents.get(operation_id)
        except (RuntimeError, ConfigurationError):
            return None

    @staticmethod
    def _operator_status_from_intent(
        intent: Any,
        *,
        applied: bool,
        preexisting_operation: bool,
    ) -> tuple[OrderMutationStatus, str]:
        """Map durable placement state to the public mutation result contract."""
        intent_state = str(intent.state)
        status = (
            OrderMutationStatus.APPLIED if applied else OrderMutationStatus.REJECTED
        )
        reason_code = str(intent.reason_code or intent_state)
        if (
            intent_state == PlacementIntentState.COMPLETED.value
            and preexisting_operation
        ):
            return OrderMutationStatus.DEDUPLICATED, "duplicate_operation"
        if intent_state in {
            PlacementIntentState.INDETERMINATE.value,
            PlacementIntentState.RECONCILING.value,
            PlacementIntentState.ACCEPTED.value,
            PlacementIntentState.FILLED.value,
            PlacementIntentState.PERSISTED.value,
        }:
            return OrderMutationStatus.INDETERMINATE, reason_code
        if intent_state in {
            PlacementIntentState.QUARANTINED.value,
            PlacementIntentState.RESTORED_QUARANTINED.value,
        }:
            return OrderMutationStatus.QUARANTINED, reason_code
        if intent_state == PlacementIntentState.REJECTED.value:
            return OrderMutationStatus.REJECTED, reason_code
        return status, reason_code

    @classmethod
    def _operator_result_from_intent(
        cls,
        *,
        intent: Any,
        operation_id: str,
        symbol: str,
        action: str,
        applied: bool,
        preexisting_operation: bool,
    ) -> OrderMutationResult:
        """Build an operator-visible result from the resolved durable intent."""
        status, reason_code = cls._operator_status_from_intent(
            intent,
            applied=applied,
            preexisting_operation=preexisting_operation,
        )
        messages = {
            OrderMutationStatus.APPLIED: "The order was applied.",
            OrderMutationStatus.DEDUPLICATED: (
                "This operation was already completed; no duplicate order was sent."
            ),
            OrderMutationStatus.REJECTED: "The order was rejected before completion.",
            OrderMutationStatus.STALE: (
                "Trade state changed before execution. Refresh and try again."
            ),
            OrderMutationStatus.INDETERMINATE: (
                "The exchange outcome is not yet known. Reconciliation is required."
            ),
            OrderMutationStatus.QUARANTINED: (
                "The operation is quarantined and requires operator review."
            ),
        }
        return OrderMutationResult(
            operation_id=operation_id,
            symbol=symbol,
            action=action,
            status=status,
            reason_code=reason_code,
            exchange_order_id=str(intent.exchange_order_id or "") or None,
            client_order_id=str(intent.client_order_id or "") or None,
            user_message=messages[status],
        )

    async def _snapshot_is_current(
        self,
        expected: LifecycleSnapshotIdentity | None,
        symbol: str,
        config: dict[str, Any],
    ) -> bool:
        """Fail closed when locked lifecycle state differs from evaluation."""
        if expected is None:
            return True
        current_trade = await self._load_fresh_trade(symbol)
        if snapshots_match(expected, current_trade, config):
            return True
        logging.info(
            "Rejecting lifecycle mutation for %s: stale_snapshot.",
            symbol,
        )
        return False

    async def _order_snapshot_is_current(
        self,
        order: dict[str, Any],
        config: dict[str, Any],
    ) -> bool:
        """Validate and compare an order's optional lifecycle snapshot."""
        if order.get("lifecycle_snapshot") is None:
            return True
        expected = self._expected_lifecycle_snapshot(order)
        if expected is None:
            return False
        return await self._snapshot_is_current(
            expected,
            str(order.get("symbol") or ""),
            config,
        )

    async def _get_sidestep_campaigns(self) -> SpotSidestepCampaignService:
        """Return the shared sidestep campaign service instance."""
        if self.sidestep_campaigns is None:
            self.sidestep_campaigns = await SpotSidestepCampaignService.instance()
        return self.sidestep_campaigns

    async def reconcile_placement_intents(
        self,
        config: dict[str, Any],
    ) -> PlacementReconciliationSummary:
        """Reconcile durable exchange effects before runtime producers start."""
        recovery = PlacementRecoveryHandler(
            exchange=self.exchange,
            trades=self.trades,
            validate_buy=self._has_valid_buy_fill,
            validate_sell=self._is_sold_check_status,
            finalize_buy=self._finalize_buy_order,
            finalize_sell=self._finalize_completed_sell,
            build_limit_sell_payload=self._build_tp_limit_sell_payload,
            persist_limit_fallback=self._persist_reconciled_limit_fallback,
        )
        reconciler = PlacementReconciler(
            self.exchange,
            recovery.resume,
            self.placement_intents,
        )
        try:
            return await reconciler.reconcile(config)
        finally:
            await self.exchange.close()

    async def _persist_reconciled_limit_fallback(
        self,
        limit_status: dict[str, Any],
        config: dict[str, Any],
        operation_id: str,
    ) -> bool:
        """Persist a recovered partial limit fill without replaying fallback."""
        partial_status = build_partial_status_from_fallback(
            limit_status,
            default_symbol=str(limit_status.get("symbol") or ""),
        )
        if float(partial_status.get("partial_filled_amount") or 0.0) <= 0:
            return False
        await self.__handle_partial_sell_status(
            partial_status,
            config,
            placement_operation_id=operation_id,
        )
        return True

    @staticmethod
    def _parse_metadata_json(raw_value: Any) -> dict[str, Any]:
        """Return structured order metadata from a JSON payload when possible."""
        if isinstance(raw_value, dict):
            return dict(raw_value)
        if not isinstance(raw_value, str) or not raw_value.strip():
            return {}
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _build_entry_size_retry_order(
        self,
        order: dict[str, Any],
        precheck: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Return a one-shot baseline retry order for entry-sizing failures."""
        if not bool(order.get("baseorder")) or not bool(
            order.get("entry_size_applied")
        ):
            return None

        reason = str((precheck or {}).get("reason") or "")
        if reason not in self._ENTRY_SIZING_RETRY_REASONS:
            return None

        baseline_order_size = float(order.get("baseline_order_size") or 0.0)
        current_order_size = float(order.get("ordersize") or 0.0)
        if (
            baseline_order_size <= 0
            or abs(current_order_size - baseline_order_size) < 1e-12
        ):
            return None

        retry_order = dict(order)
        retry_order["ordersize"] = baseline_order_size
        retry_order["entry_size_applied"] = False
        retry_order["entry_size_fallback_applied"] = True
        retry_order["entry_size_fallback_reason"] = reason

        metadata = self._parse_metadata_json(order.get("metadata_json"))
        entry_sizing = metadata.get("entry_sizing")
        if not isinstance(entry_sizing, dict):
            entry_sizing = {}
        entry_sizing["applied"] = False
        entry_sizing["fallback_applied"] = True
        entry_sizing["fallback_reason_code"] = reason
        entry_sizing["resolved_order_size"] = baseline_order_size
        metadata["entry_sizing"] = entry_sizing
        retry_order["metadata_json"] = json.dumps(metadata, sort_keys=True)
        return retry_order

    async def _finalize_buy_order(
        self,
        order_status: ExchangeOrderPayload,
        config: dict[str, Any],
        *,
        original_order: dict[str, Any],
        placement_operation_id: str | None = None,
    ) -> bool:
        """Persist a filled buy order and emit monitoring."""
        logging.debug(order_status)
        if not self._has_valid_buy_fill(order_status):
            logging.error(
                "Skipping trade creation for %s: invalid order status.",
                order_status.get("symbol"),
            )
            return False
        for key in (
            "campaign_id",
            "signal_name",
            "strategy_name",
            "strategy_slug",
            "strategy_version",
            "timeframe",
            "metadata_json",
            "baseline_order_size",
            "entry_size_applied",
            "entry_size_reason_code",
            "entry_size_fallback_applied",
            "entry_size_fallback_reason",
        ):
            if order_status.get(key) is None and original_order.get(key) is not None:
                order_status[key] = original_order[key]
        if bool(order_status.get("safetyorder")):
            metadata = self._parse_metadata_json(order_status.get("metadata_json"))
            recovery_so = metadata.get("recovery_so")
            if isinstance(recovery_so, dict):
                fill_price = float(order_status.get("price") or 0.0)
                reference_price = float(recovery_so.get("reference_price") or 0.0)
                trigger_market_price = float(recovery_so.get("current_price") or 0.0)
                recovery_so["fill_price"] = fill_price
                if reference_price > 0 and fill_price > 0:
                    recovery_so["fill_deviation_percent"] = round(
                        ((fill_price - reference_price) / reference_price) * 100,
                        8,
                    )
                if trigger_market_price > 0 and fill_price > 0:
                    recovery_so["fill_vs_trigger_percent"] = round(
                        ((fill_price - trigger_market_price) / trigger_market_price)
                        * 100,
                        8,
                    )
                metadata["recovery_so"] = recovery_so
                order_status["metadata_json"] = json.dumps(metadata, sort_keys=True)
        if bool(order_status.get("baseorder")):
            metadata = self._parse_metadata_json(order_status.get("metadata_json"))
            metadata["dca_policy"] = build_recovery_sizing_policy(config).to_dict()
            order_status["metadata_json"] = json.dumps(metadata, sort_keys=True)
        payload = build_buy_trade_payload(order_status)
        sidestep_campaigns = await self._get_sidestep_campaigns()
        campaign_context = await sidestep_campaigns.resolve_buy_context(
            order_status["symbol"],
            original_order,
            config,
        )
        if str(campaign_context.get("campaign_id") or "").strip():
            logging.info(
                "Persisting campaign buy for %s: campaign=%s strategy=%s signal=%s.",
                order_status["symbol"],
                campaign_context.get("campaign_id"),
                original_order.get("strategy_name"),
                original_order.get("signal_name"),
            )
        persistence_options: dict[str, Any] = {
            "create_open_trade": not bool(order_status["safetyorder"]),
            "campaign_context": campaign_context,
            "entry_evaluation": original_order.get("_ai_entry_evaluation"),
        }
        if placement_operation_id:
            persistence_options["placement_operation_id"] = placement_operation_id
        await persist_buy_trade(
            order_status["symbol"],
            payload,
            **persistence_options,
        )
        await self._reset_unsellable_state(order_status["symbol"])
        await self.monitoring.notify_trade(
            "trade.buy",
            build_buy_monitor_payload(order_status),
            config,
        )
        return True

    @staticmethod
    def _log_buy_failure(
        symbol: str,
        precheck: dict[str, Any] | None,
    ) -> None:
        """Emit the shared failure log for an unfilled buy order."""
        if precheck and not bool(precheck.get("ok", False)):
            logging.warning(
                "Skipping buy order for %s: buy pre-check failed (%s). required=%s available=%s",
                symbol,
                precheck.get("reason", "unknown"),
                precheck.get("required_quote"),
                precheck.get("available_quote"),
            )
            return
        logging.error("Failed creating buy order for %s", symbol)

    @staticmethod
    def _is_exchange_order_filled(status: dict[str, Any]) -> bool:
        """Return whether an exchange order status represents a completed fill."""
        order_status = str(status.get("status") or "").lower()
        filled = float(status.get("filled") or 0.0)
        amount = float(status.get("amount") or 0.0)
        return order_status in {"closed", "filled"} or (amount > 0 and filled >= amount)

    @staticmethod
    def _is_exchange_order_inactive(status: dict[str, Any]) -> bool:
        """Return whether an exchange order is safely no longer open."""
        order_status = str(status.get("status") or "").lower()
        return order_status in {"canceled", "cancelled", "rejected", "expired"}

    def _build_tp_limit_sell_payload(
        self,
        trades: dict[str, Any],
        exchange_status: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a sell payload for a filled proactive TP limit order."""
        fallback_price = float(
            exchange_status.get("average")
            or exchange_status.get("price")
            or trades.get("tp_limit_order_price")
            or trades.get("tp_price")
            or trades.get("current_price")
            or 0.0
        )
        amount = float(
            exchange_status.get("filled")
            or exchange_status.get("amount")
            or trades.get("tp_limit_order_amount")
            or trades.get("total_amount")
            or 0.0
        )
        cost = float(exchange_status.get("cost") or amount * fallback_price)
        timestamp = int(
            exchange_status.get("timestamp") or datetime.now().timestamp() * 1000
        )
        actual_pnl = self.utils.calculate_actual_pnl(trades, fallback_price)
        return {
            "id": str(exchange_status.get("id") or trades["tp_limit_order_id"]),
            "symbol": str(exchange_status.get("symbol") or trades["symbol"]),
            "side": str(exchange_status.get("side") or "sell"),
            "ordertype": str(exchange_status.get("type") or "limit"),
            "amount": amount,
            "total_amount": amount,
            "requested_total_amount": float(
                trades.get("sellable_amount") or trades.get("total_amount") or amount
            ),
            "price": fallback_price,
            "cost": cost,
            "timestamp": timestamp,
            "fee": exchange_status.get("fee") or 0.0,
            "total_cost": float(trades.get("total_cost") or 0.0),
            "actual_pnl": actual_pnl,
        }

    async def _finalize_completed_sell(
        self,
        order_status: SoldCheckStatus,
        config: dict[str, Any],
        *,
        placement_operation_id: str | None = None,
        placement_operation_ids: list[str] | None = None,
    ) -> None:
        """Persist a completed sell status and emit monitoring."""
        normalized_close_reason = SpotSidestepCampaignService.normalize_close_reason(
            order_status.get("close_reason")
        )
        order_status["close_reason"] = normalized_close_reason
        closed_at = (
            trade_datetime_from_ms(float(order_status["timestamp"]))
            if order_status.get("timestamp") is not None
            else datetime.now(timezone.utc)
        )
        close_context = await self.__calculate_closed_trade_stats(order_status)
        sidestep_campaigns = await self._get_sidestep_campaigns()
        campaign_context = await sidestep_campaigns.resolve_close_context(
            order_status["symbol"],
            normalized_close_reason,
            config,
            closed_at=closed_at,
            closed_payload=close_context["payload"],
        )
        if normalized_close_reason == TradeCloseReason.SIDESTEP_EXIT.value:
            logging.info(
                "Persisting sidestep transition for %s: campaign=%s -> flat waiting.",
                order_status["symbol"],
                campaign_context.get("campaign_id"),
            )
            sidestep_options: dict[str, Any] = {
                "campaign_context": campaign_context,
            }
            if placement_operation_id:
                sidestep_options["placement_operation_id"] = placement_operation_id
            if placement_operation_ids:
                sidestep_options["placement_operation_ids"] = placement_operation_ids
            await persist_sidestep_transition(
                order_status["symbol"],
                close_context["payload"],
                **sidestep_options,
            )
        else:
            close_options: dict[str, Any] = {
                "campaign_context": campaign_context,
            }
            if placement_operation_id:
                close_options["placement_operation_id"] = placement_operation_id
            if placement_operation_ids:
                close_options["placement_operation_ids"] = placement_operation_ids
            await persist_closed_trade(
                order_status["symbol"],
                close_context["payload"],
                **close_options,
            )
        await self.trades.invalidate_trade_caches()
        await self.monitoring.notify_trade(
            "trade.sell",
            close_context["monitor_payload"],
            config,
        )

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
            if self._is_exchange_order_filled(exchange_status):
                payload = self._build_tp_limit_sell_payload(trades, exchange_status)
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
                if not self._is_sold_check_status(order_status):
                    if self._is_partial_sell_status(order_status):
                        await self.__handle_partial_sell_status(order_status, config)
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
                await self._finalize_completed_sell(order_status, config)
                logging.info(
                    "Closed %s from proactive TP limit order %s.",
                    symbol,
                    order_id,
                )
                return True
            if self._is_exchange_order_inactive(exchange_status):
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
            if not await self._snapshot_is_current(
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
            if exchange_status and self._is_exchange_order_filled(exchange_status):
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.FILLED,
                    exchange_order_id=order_id,
                    result=dict(exchange_status),
                )
                if trade_data:
                    payload = self._build_tp_limit_sell_payload(
                        trade_data,
                        exchange_status,
                    )
                    order_status = await self.exchange.build_spot_sell_order_status(
                        payload,
                        config,
                    )
                    if order_status and self._is_sold_check_status(order_status):
                        await self._finalize_completed_sell(
                            order_status,
                            config,
                            placement_operation_id=placement.operation_id,
                        )
                    elif order_status and self._is_partial_sell_status(order_status):
                        await self.__handle_partial_sell_status(
                            order_status,
                            config,
                            placement_operation_id=placement.operation_id,
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

            if self._is_exchange_order_inactive(exchange_status):
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
        if not await self._snapshot_is_current(
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
            if not await self._order_snapshot_is_current(order, config):
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
                    order_status = await self.exchange.place_spot_limit_sell(
                        order,
                        config,
                    )
                except ExchangePostSubmissionFailure as exc:
                    active_operation_id = str(
                        exc.operation_id or placement.operation_id or ""
                    )
                    await self.placement_intents.transition(
                        active_operation_id,
                        PlacementIntentState.ACCEPTED,
                        exchange_order_id=str(exc.order.get("id") or "") or None,
                        result=exc.order,
                        reason_code="local_finalization_pending",
                        error_message=str(exc.cause or exc),
                    )
                    logging.error(
                        "Sell submission for %s was accepted but could not be "
                        "finalized locally; operation=%s requires reconciliation.",
                        order.get("symbol"),
                        active_operation_id,
                        exc_info=True,
                    )
                    return False
                except ExchangeSubmissionIndeterminate as exc:
                    await self.placement_intents.transition(
                        placement.operation_id,
                        PlacementIntentState.INDETERMINATE,
                        reason_code="exchange_response_lost",
                        error_message=str(exc),
                    )
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
                        await self.__handle_partial_sell_status(
                            partial_status,
                            config,
                            placement_operation_id=placement.operation_id,
                        )
                    logging.info(
                        "Proactive TP limit order for %s was not armed: %s",
                        symbol,
                        order_status,
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

        if not self._is_exchange_order_inactive(exchange_status):
            target_state = (
                PlacementIntentState.REJECTED
                if self._is_exchange_order_filled(exchange_status)
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
            persist_limit_fallback=self._persist_reconciled_limit_fallback,
            logger=logging,
        ).execute(remaining_order, config, limit_status)

    async def _receive_sell_order(
        self, order: SellIntent | dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Execute one sell order with the symbol prelocked."""
        logging.info("Incoming sell order for %s", order["symbol"])
        if order.get("sell_reason") == TradeCloseReason.SIDESTEP_EXIT.value:
            logging.info(
                "Incoming sidestep exit sell for %s: campaign=%s.",
                order["symbol"],
                order.get("campaign_id"),
            )
        async with lifecycle_mutation_coordinator.prelocked(order["symbol"]):
            try:
                if not await self._order_snapshot_is_current(order, config):
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
                    if sell_order_type == "limit":
                        order_status = await self.exchange.create_spot_sell(
                            order,
                            config,
                            create_market_fallback=(
                                self._create_durable_market_fallback
                            ),
                        )
                    else:
                        order_status = await self.exchange.create_spot_sell(
                            order,
                            config,
                        )
                except ExchangePostSubmissionFailure as exc:
                    active_operation_id = str(
                        exc.operation_id or placement.operation_id or ""
                    )
                    await self.placement_intents.transition(
                        active_operation_id,
                        PlacementIntentState.ACCEPTED,
                        exchange_order_id=str(exc.order.get("id") or "") or None,
                        result=exc.order,
                        reason_code="local_finalization_pending",
                        error_message=str(exc.cause or exc),
                    )
                    logging.error(
                        "Sell submission for %s was accepted but could not be "
                        "finalized locally; operation=%s requires reconciliation.",
                        order.get("symbol"),
                        active_operation_id,
                        exc_info=True,
                    )
                    return False
                except ExchangeSubmissionIndeterminate as exc:
                    if exc.operation_id and exc.operation_id != placement.operation_id:
                        logging.error(
                            "Market fallback for %s is indeterminate; "
                            "child operation=%s will be reconciled before retry.",
                            order.get("symbol"),
                            exc.operation_id,
                        )
                        return False
                    await self.placement_intents.transition(
                        placement.operation_id,
                        PlacementIntentState.INDETERMINATE,
                        reason_code="exchange_response_lost",
                        error_message=str(exc),
                    )
                    logging.error(
                        "Sell submission for %s is indeterminate; operation=%s "
                        "will be reconciled before any retry.",
                        order.get("symbol"),
                        placement.operation_id,
                    )
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

                if self._is_partial_sell_status(order_status):
                    if (
                        order_status.get("close_reason") is None
                        and order.get("sell_reason") is not None
                    ):
                        order_status["close_reason"] = str(order["sell_reason"])
                    if (
                        order_status.get("campaign_id") is None
                        and order.get("campaign_id") is not None
                    ):
                        order_status["campaign_id"] = str(order["campaign_id"])
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
                        await self.__handle_partial_sell_status(order_status, config)
                        return False
                    await self.placement_intents.transition(
                        active_operation_id,
                        PlacementIntentState.FILLED,
                        exchange_order_id=str(order_status.get("id") or "") or None,
                        result=dict(order_status),
                    )
                    if source_operation_id:
                        await self.__handle_partial_sell_status(
                            order_status,
                            config,
                            placement_operation_ids=persistence_operation_ids,
                        )
                    else:
                        await self.__handle_partial_sell_status(
                            order_status,
                            config,
                            placement_operation_id=active_operation_id,
                        )
                    for operation_id in persistence_operation_ids:
                        await self.placement_intents.transition(
                            operation_id,
                            PlacementIntentState.COMPLETED,
                        )
                    return True

                if not self._is_sold_check_status(order_status):
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
                if (
                    order_status.get("campaign_id") is None
                    and order.get("campaign_id") is not None
                ):
                    order_status["campaign_id"] = order["campaign_id"]

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
                    await self._finalize_completed_sell(
                        order_status,
                        config,
                        placement_operation_ids=persistence_operation_ids,
                    )
                else:
                    await self._finalize_completed_sell(
                        order_status,
                        config,
                        placement_operation_id=active_operation_id,
                    )
                for operation_id in persistence_operation_ids:
                    await self.placement_intents.transition(
                        operation_id,
                        PlacementIntentState.COMPLETED,
                    )
                return True
            finally:
                await self.exchange.close()

    async def __handle_partial_sell_status(
        self,
        order_status: PartialSellStatus,
        config: dict[str, Any],
        *,
        placement_operation_id: str | None = None,
        placement_operation_ids: list[str] | None = None,
    ) -> None:
        """Persist partial sell execution while keeping the trade open."""
        if bool(order_status.get("unsellable", False)):
            await self.__handle_unsellable_remainder(
                order_status,
                config,
                placement_operation_id=placement_operation_id,
                placement_operation_ids=placement_operation_ids,
            )
            return

        partial_amount = float(order_status.get("partial_filled_amount") or 0.0)
        partial_proceeds = float(order_status.get("partial_proceeds") or 0.0)
        if partial_amount > 0:
            partial_options: dict[str, Any] = {}
            if placement_operation_id:
                partial_options["placement_operation_id"] = placement_operation_id
            if placement_operation_ids:
                partial_options["placement_operation_ids"] = placement_operation_ids
            await persist_partial_sell_execution(
                order_status["symbol"],
                partial_amount,
                partial_proceeds,
                order_status.get("executions"),
                **partial_options,
            )
            await self.trades.invalidate_trade_caches()
            logging.info(
                "Persisted partial sell execution for %s: amount=%s proceeds=%s remaining=%s",
                order_status["symbol"],
                partial_amount,
                partial_proceeds,
                float(order_status.get("remaining_amount") or 0.0),
            )

    async def __handle_unsellable_remainder(
        self,
        order_status: PartialSellStatus,
        config: dict[str, Any],
        *,
        placement_operation_id: str | None = None,
        placement_operation_ids: list[str] | None = None,
    ) -> None:
        """Persist partial close and mark remaining amount as unsellable."""
        snapshot = build_unsellable_status_snapshot(order_status)
        if not snapshot.symbol:
            return

        closed_at = self.__resolve_partial_sell_closed_at(order_status)

        open_trade_rows = await self.trades.get_open_trades_by_symbol(snapshot.symbol)
        open_trade = open_trade_rows[0] if open_trade_rows else None
        so_count = await self.__resolve_so_count(snapshot.symbol)
        open_timestamp = (
            await self.__resolve_open_timestamp(snapshot.symbol)
            if snapshot.partial_amount > 0
            else None
        )
        context = build_unsellable_remainder_context(
            snapshot,
            open_trade=open_trade,
            so_count=so_count,
            open_timestamp_ms=open_timestamp,
            closed_at=closed_at,
            unsellable_since=closed_at.isoformat(),
        )

        normalized_close_reason = SpotSidestepCampaignService.normalize_close_reason(
            order_status.get("close_reason")
        )

        if (
            normalized_close_reason == TradeCloseReason.SIDESTEP_EXIT.value
            and context.closed_trade_payload is not None
        ):
            sidestep_campaigns = await self._get_sidestep_campaigns()
            sidestep_payload = {
                **context.closed_trade_payload,
                "close_reason": normalized_close_reason,
                "sell_executions": list(snapshot.partial_executions),
            }
            campaign_context = await sidestep_campaigns.resolve_close_context(
                snapshot.symbol,
                normalized_close_reason,
                config,
                closed_at=closed_at,
                closed_payload=sidestep_payload,
            )
            logging.info(
                "Persisting sidestep transition for %s with unsellable remainder: campaign=%s -> flat waiting.",
                snapshot.symbol,
                campaign_context.get("campaign_id"),
            )
            await persist_sidestep_transition(
                snapshot.symbol,
                sidestep_payload,
                campaign_context=campaign_context,
                unsellable_payload=context.unsellable_payload,
                placement_operation_id=placement_operation_id,
                placement_operation_ids=placement_operation_ids,
            )
            await self.trades.invalidate_trade_caches()
            if not context.already_notified:
                await self.monitoring.notify_trade(
                    "trade.unsellable_notional",
                    context.monitor_payload,
                    config,
                )
            logging.warning(
                "Marked %s remainder as unsellable (reason=%s, remaining=%s, min_notional=%s, estimated_notional=%s).",
                context.symbol,
                context.reason,
                context.remaining_amount,
                context.min_notional,
                context.estimated_notional,
            )
            return

        await persist_unsellable_remainder(
            snapshot.symbol,
            context.unsellable_payload,
            partial_amount=context.partial_amount,
            partial_proceeds=context.partial_proceeds,
            sell_executions=snapshot.partial_executions,
            closed_trade_payload=context.closed_trade_payload,
            placement_operation_id=placement_operation_id,
            placement_operation_ids=placement_operation_ids,
        )
        await self.trades.invalidate_trade_caches()

        if not context.already_notified:
            await self.monitoring.notify_trade(
                "trade.unsellable_notional",
                context.monitor_payload,
                config,
            )
        logging.warning(
            "Marked %s remainder as unsellable (reason=%s, remaining=%s, min_notional=%s, estimated_notional=%s).",
            context.symbol,
            context.reason,
            context.remaining_amount,
            context.min_notional,
            context.estimated_notional,
        )

    @staticmethod
    def __resolve_partial_sell_closed_at(
        order_status: PartialSellStatus,
    ) -> datetime:
        """Return the best-effort close timestamp for a partial sell status."""
        for execution in order_status.get("executions", []) or []:
            raw_timestamp = execution.get("timestamp")
            if raw_timestamp in (None, ""):
                continue
            try:
                return trade_datetime_from_ms(float(raw_timestamp))
            except (TypeError, ValueError):
                continue
        return datetime.now(timezone.utc)

    async def __calculate_closed_trade_stats(
        self, order_status: SoldCheckStatus
    ) -> dict[str, Any]:
        """Build closed-trade payload and monitoring payload."""
        symbol = order_status["symbol"]
        open_timestamp = await self.__resolve_open_timestamp(symbol)
        so_count = await self.__resolve_so_count(symbol)
        partial_amount, partial_proceeds = await self.trades.get_partial_sell_execution(
            symbol
        )

        return build_closed_trade_payloads(
            order_status,
            so_count=so_count,
            open_timestamp_ms=open_timestamp,
            partial_amount=partial_amount,
            partial_proceeds=partial_proceeds,
        )

    async def __resolve_open_timestamp(self, symbol: str) -> float:
        """Resolve base-order timestamp for trade duration calculation."""
        base_order = await self.trades.get_trade_by_ordertype(symbol, baseorder=True)
        try:
            return float(base_order[0]["timestamp"])
        except (IndexError, KeyError, TypeError, ValueError) as e:
            logging.debug(
                "Did not found a timestamp - taking default value. Cause %s", e
            )
            return datetime.now().timestamp() * 1000

    async def __resolve_so_count(self, symbol: str) -> int:
        """Resolve safety-order count from open trade row."""
        open_trade = await self.trades.get_open_trades_by_symbol(symbol)
        if open_trade:
            return int(open_trade[0]["so_count"])
        return 0

    @staticmethod
    def _is_partial_sell_status(
        order_status: dict[str, Any],
    ) -> TypeGuard[PartialSellStatus]:
        """Return whether an exchange sell result is a partial-sell status."""
        return str(order_status.get("type") or "") == "partial_sell"

    @staticmethod
    def _is_sold_check_status(
        order_status: dict[str, Any],
    ) -> TypeGuard[SoldCheckStatus]:
        """Return whether an exchange sell result is a finalized sell status."""
        status_type = str(order_status.get("type") or "")
        if status_type == "sold_check":
            return True
        return (
            status_type == ""
            and bool(order_status.get("symbol"))
            and bool(order_status.get("total_amount"))
        )

    @staticmethod
    def _has_valid_buy_fill(order_status: ExchangeOrderPayload) -> bool:
        """Validate that an exchange buy payload contains the core filled values."""
        return (
            bool(order_status.get("price"))
            and bool(order_status.get("amount"))
            and (float(order_status["amount"]) > 0)
        )

    async def _reset_unsellable_state(self, symbol: str) -> None:
        """Clear persisted unsellable markers after a successful buy."""
        try:
            await self.trades.update_open_trades(
                {
                    "unsellable_amount": 0.0,
                    "unsellable_reason": None,
                    "unsellable_min_notional": None,
                    "unsellable_estimated_notional": None,
                    "unsellable_since": None,
                    "unsellable_notice_sent": False,
                },
                symbol,
            )
        except (RuntimeError, ConfigurationError):
            # Tests may stub persistence without initializing DB context.
            pass

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
        if not await self._order_snapshot_is_current(order, config):
            return False
        if str(order.get("campaign_id") or "").strip():
            logging.info(
                "Incoming campaign buy order for %s: campaign=%s strategy=%s signal=%s.",
                order["symbol"],
                order.get("campaign_id"),
                order.get("strategy_name"),
                order.get("signal_name"),
            )

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
            retry_order = self._build_entry_size_retry_order(order, precheck)
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

            self._log_buy_failure(order["symbol"], precheck)
            return False
        finally:
            await self.exchange.close()

    async def _execute_budgeted_buy_order(
        self,
        order: dict[str, Any],
        config: dict[str, Any],
    ) -> tuple[bool, dict[str, Any] | None]:
        """Run capital-budget preflight, exchange buy, and persistence."""
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
                order_status = await self.exchange.create_spot_market_buy(
                    order,
                    config,
                )
            except ExchangePostSubmissionFailure as exc:
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.ACCEPTED,
                    exchange_order_id=str(exc.order.get("id") or "") or None,
                    result=exc.order,
                    reason_code="local_finalization_pending",
                    error_message=str(exc.cause or exc),
                )
                logging.error(
                    "Buy submission for %s was accepted but could not be "
                    "finalized locally; operation=%s requires reconciliation.",
                    order.get("symbol"),
                    placement.operation_id,
                    exc_info=True,
                )
                return (
                    False,
                    {
                        "ok": False,
                        "reason": "placement_reconciliation_pending",
                        "symbol": str(order.get("symbol") or ""),
                    },
                )
            except ExchangeSubmissionIndeterminate as exc:
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.INDETERMINATE,
                    reason_code="exchange_response_lost",
                    error_message=str(exc),
                )
                logging.error(
                    "Buy submission for %s is indeterminate; operation=%s will "
                    "be reconciled before any retry.",
                    order.get("symbol"),
                    placement.operation_id,
                )
                return (
                    False,
                    {
                        "ok": False,
                        "reason": "placement_indeterminate",
                        "symbol": str(order.get("symbol") or ""),
                    },
                )
            if not order_status:
                precheck = self.exchange.get_last_buy_precheck_result()
                await self.placement_intents.transition(
                    placement.operation_id,
                    PlacementIntentState.REJECTED,
                    reason_code=str((precheck or {}).get("reason") or "not_filled"),
                )
                return False, precheck
            if not self._has_valid_buy_fill(order_status):
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
            finalized = await self._finalize_buy_order(
                order_status,
                config,
                original_order=order,
                placement_operation_id=placement.operation_id,
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
                if not await self._snapshot_is_current(
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
        try:
            trade = await self._load_authoritative_trade(normalized_symbol)
        except TradeStateUnavailableError:
            return self._trade_state_unavailable_result(
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
            current_trade = await self._load_fresh_trade(normalized_symbol)
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
        """Stop one symbol with the symbol prelocked."""
        logging.info("Incoming stop order")
        symbol = normalize_order_symbol(symbol)
        lifecycle_mutation_coordinator.assert_prelocked(symbol)
        try:
            canceled = await self._cancel_tp_limit_order_locked(
                symbol,
                config or {},
            )
            if not canceled:
                return False
            sidestep_campaigns = await self._get_sidestep_campaigns()
            campaign_context = await sidestep_campaigns.resolve_close_context(
                symbol,
                "manual_stop",
                config or {},
                closed_at=datetime.now(timezone.utc),
            )
            await persist_stopped_trade(symbol, campaign_context=campaign_context)
            await self.trades.invalidate_trade_caches()
            return True
        except (
            ConfigurationError,
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
            )
            return False

    async def receive_sell_signal(self, symbol: str, config: dict[str, Any]) -> bool:
        """Handle a manual sell signal."""
        symbol = normalize_order_symbol(symbol)
        trades = await self.trades.get_trades_for_orders(symbol)
        if not trades:
            logging.error("No running trade found for manual sell of %s.", symbol)
            return False

        actual_pnl = self.utils.calculate_actual_pnl(trades)
        order = build_manual_sell_order_intent(trades, actual_pnl)
        return await self.receive_sell_order(order, config)

    async def _operator_mutation_result(
        self,
        *,
        order: dict[str, Any],
        action: str,
        applied: bool,
        preexisting_operation: bool,
        expected_snapshot: LifecycleSnapshotIdentity,
        config: dict[str, Any],
    ) -> OrderMutationResult:
        """Resolve a stable API outcome from lifecycle and placement state."""
        operation_id = str(order.get("operation_id") or "")
        intent = (
            await self._get_placement_intent(operation_id) if operation_id else None
        )

        status = (
            OrderMutationStatus.APPLIED if applied else OrderMutationStatus.REJECTED
        )
        reason_code = "mutation_applied" if applied else "mutation_rejected"
        if intent is not None:
            return self._operator_result_from_intent(
                intent=intent,
                operation_id=operation_id,
                symbol=expected_snapshot.symbol,
                action=action,
                applied=applied,
                preexisting_operation=preexisting_operation,
            )
        elif not applied:
            try:
                current_trade = await self._load_authoritative_trade(
                    expected_snapshot.symbol
                )
            except TradeStateUnavailableError:
                return self._trade_state_unavailable_result(
                    operation_id=operation_id,
                    symbol=expected_snapshot.symbol,
                    action=action,
                )
            if not snapshots_match(expected_snapshot, current_trade, config):
                status = OrderMutationStatus.STALE
                reason_code = "stale_snapshot"

        messages = {
            OrderMutationStatus.APPLIED: "The order was applied.",
            OrderMutationStatus.DEDUPLICATED: (
                "This operation was already completed; no duplicate order was sent."
            ),
            OrderMutationStatus.REJECTED: "The order was rejected before completion.",
            OrderMutationStatus.STALE: (
                "Trade state changed before execution. Refresh and try again."
            ),
            OrderMutationStatus.INDETERMINATE: (
                "The exchange outcome is not yet known. Reconciliation is required."
            ),
            OrderMutationStatus.QUARANTINED: (
                "The operation is quarantined and requires operator review."
            ),
        }
        return OrderMutationResult(
            operation_id=operation_id,
            symbol=expected_snapshot.symbol,
            action=action,
            status=status,
            reason_code=reason_code,
            exchange_order_id=(
                str(intent.exchange_order_id or "") or None
                if intent is not None
                else None
            ),
            client_order_id=(
                str(intent.client_order_id or "") or None
                if intent is not None
                else None
            ),
            user_message=messages[status],
        )

    async def receive_sell_signal_result(
        self,
        symbol: str,
        config: dict[str, Any],
        *,
        operation_id: str | None = None,
    ) -> OrderMutationResult:
        """Handle a manual sell and report its durable execution outcome."""
        symbol = normalize_order_symbol(symbol)
        try:
            trades = await self._load_authoritative_trade(symbol)
        except TradeStateUnavailableError:
            return self._trade_state_unavailable_result(
                operation_id=operation_id,
                symbol=symbol,
                action="manual_sell",
            )
        if not trades:
            if operation_id:
                existing = await self._get_placement_intent(str(operation_id))
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
        preexisting = await self._get_placement_intent(order["operation_id"])
        applied = await self.receive_sell_order(order, config)
        return await self._operator_mutation_result(
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
        if operation_id:
            existing = await self._get_placement_intent(str(operation_id))
            if existing is not None:
                return self._operator_result_from_intent(
                    intent=existing,
                    operation_id=str(operation_id),
                    symbol=symbol,
                    action="manual_buy",
                    applied=False,
                    preexisting_operation=True,
                )
        try:
            trades = await self._load_authoritative_trade(symbol)
        except TradeStateUnavailableError:
            return self._trade_state_unavailable_result(
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
        preexisting = await self._get_placement_intent(order["operation_id"])
        applied = await self.receive_buy_order(order, config)
        return await self._operator_mutation_result(
            order=order,
            action="manual_buy",
            applied=applied,
            preexisting_operation=preexisting is not None,
            expected_snapshot=snapshot,
            config=config,
        )
