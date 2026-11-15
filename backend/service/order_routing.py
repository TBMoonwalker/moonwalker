"""Mode-neutral order lifecycle routing: ownership guard and operator results.

Owns the lifecycle-ownership rejection, snapshot currency validation, trade
state loading, and the operator mutation-result contract. DCA execution and
finalization live in service/dca/; this class is shared by
PlacementRecoveryEntry and DcaOrderLifecycle.
"""

import sqlite3
from typing import Any

import helper
from service.lifecycle_routing import LifecycleRoute, load_lifecycle_route
from service.lifecycle_snapshot import (
    LifecycleSnapshotIdentity,
    snapshots_match,
)
from service.order_mutation_result import (
    OrderMutationResult,
    OrderMutationStatus,
)
from service.placement_intents import PlacementIntentState
from service.trades import Trades, TradeStateUnavailableError
from tortoise.exceptions import BaseORMException, ConfigurationError

logging = helper.LoggerFactory.get_logger("logs/orders.log", "orders")


class OrderLifecycleRouting:
    """Reject non-DCA mutations, validate snapshots, and map operator results."""

    def __init__(self, *, trades: Trades, placement_intents: Any) -> None:
        self.trades = trades
        self.placement_intents = placement_intents

    async def reject_legacy_lifecycle(
        self,
        symbol: str,
        action: str,
        operation_id: str | None = None,
    ) -> OrderMutationResult | None:
        """Reject non-DCA ownership without trusting order payload mode/reason.

        Accumulation uses dedicated lifecycle-authorized execution. Legacy manual endpoints are not a bypass.
        Reconciliation and cancellation of existing orders remain available.
        """
        try:
            decision = await load_lifecycle_route(symbol)
        except (BaseORMException, RuntimeError, sqlite3.Error, ValueError):
            logging.error(
                "Cannot resolve lifecycle ownership for %s.", symbol, exc_info=True
            )
            return self.trade_state_unavailable_result(
                operation_id=operation_id, symbol=symbol, action=action
            )
        if decision.route == LifecycleRoute.CLASSIC_DCA:
            return None
        accumulation = decision.route == LifecycleRoute.ACCUMULATION
        reason = "accumulation_lifecycle_required" if accumulation else decision.reason
        message = (
            "This symbol belongs to accumulation. Use its strategy and explicit "
            "lifecycle actions in Trading Overview."
            if accumulation
            else "Lifecycle ownership is invalid. No mutation was performed; repair the state first."
        )
        logging.warning("Rejecting legacy %s for %s: %s.", action, symbol, reason)
        return OrderMutationResult(
            operation_id=str(operation_id or ""),
            symbol=symbol,
            action=action,
            status=OrderMutationStatus.REJECTED,
            reason_code=reason,
            user_message=message,
        )

    @staticmethod
    def expected_lifecycle_snapshot(
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

    async def load_fresh_trade(self, symbol: str) -> dict[str, Any] | None:
        """Reload authoritative trade state without the dashboard TTL cache."""
        fresh_loader = getattr(self.trades, "get_trades_for_orders_fresh", None)
        if callable(fresh_loader):
            return await fresh_loader(symbol)
        return await self.trades.get_trades_for_orders(symbol)

    async def load_authoritative_trade(self, symbol: str) -> dict[str, Any] | None:
        """Load mutation state without converting database failures to absence."""
        authoritative_loader = getattr(
            self.trades,
            "get_trades_for_orders_authoritative",
            None,
        )
        if callable(authoritative_loader):
            return await authoritative_loader(symbol)
        return await self.load_fresh_trade(symbol)

    @staticmethod
    def trade_state_unavailable_result(
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

    async def get_placement_intent(self, operation_id: str) -> Any | None:
        """Read a durable intent when persistence is available."""
        try:
            return await self.placement_intents.get(operation_id)
        except (RuntimeError, ConfigurationError):
            return None

    @staticmethod
    def operator_status_from_intent(
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

    @staticmethod
    def operator_result_from_intent(
        *,
        intent: Any,
        operation_id: str,
        symbol: str,
        action: str,
        applied: bool,
        preexisting_operation: bool,
    ) -> OrderMutationResult:
        """Build an operator-visible result from the resolved durable intent."""
        status, reason_code = OrderLifecycleRouting.operator_status_from_intent(
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

    async def snapshot_is_current(
        self,
        expected: LifecycleSnapshotIdentity | None,
        symbol: str,
        config: dict[str, Any],
    ) -> bool:
        """Fail closed when locked lifecycle state differs from evaluation."""
        if expected is None:
            return True
        current_trade = await self.load_fresh_trade(symbol)
        if snapshots_match(expected, current_trade, config):
            return True
        logging.info(
            "Rejecting lifecycle mutation for %s: stale_snapshot.",
            symbol,
        )
        return False

    async def order_snapshot_is_current(
        self,
        order: dict[str, Any],
        config: dict[str, Any],
    ) -> bool:
        """Validate and compare an order's optional lifecycle snapshot."""
        if order.get("lifecycle_snapshot") is None:
            return True
        expected = self.expected_lifecycle_snapshot(order)
        if expected is None:
            return False
        return await self.snapshot_is_current(
            expected,
            str(order.get("symbol") or ""),
            config,
        )

    async def operator_mutation_result(
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
        intent = await self.get_placement_intent(operation_id) if operation_id else None

        status = (
            OrderMutationStatus.APPLIED if applied else OrderMutationStatus.REJECTED
        )
        reason_code = "mutation_applied" if applied else "mutation_rejected"
        if intent is not None:
            return self.operator_result_from_intent(
                intent=intent,
                operation_id=operation_id,
                symbol=expected_snapshot.symbol,
                action=action,
                applied=applied,
                preexisting_operation=preexisting_operation,
            )
        elif not applied:
            try:
                current_trade = await self.load_authoritative_trade(
                    expected_snapshot.symbol
                )
            except TradeStateUnavailableError:
                return self.trade_state_unavailable_result(
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
