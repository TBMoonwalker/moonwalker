"""Compatibility facade composing mode-neutral order routing and the DCA lifecycle.

DCA execution and trade finalization live in service/dca/; lifecycle routing,
snapshot validation and the operator mutation-result contract live in
service/order_routing.py. This facade keeps the shared collaborator identities
used by the runtime service graph and the repair-only startup path.
"""

import helper
from service.dca.finalization import (
    build_tp_limit_sell_payload,
    finalize_buy_order,
    finalize_completed_sell,
    has_valid_buy_fill,
    is_sold_check_status,
    persist_reconciled_limit_fallback,
)
from service.dca.order_lifecycle import (
    DcaOrderLifecycle,
    build_default_order_collaborators,
)
from service.order_routing import OrderLifecycleRouting
from service.placement_reconciliation import (
    PlacementReconciler,
    PlacementReconciliationSummary,
    RecoverAccumulation,
)
from service.placement_recovery import PlacementRecoveryHandler
from service.placement_repair import PlacementRepairService

logging = helper.LoggerFactory.get_logger("logs/orders.log", "orders")


class Orders:
    """Handle incoming buy/sell signals and persist trades."""

    def __init__(self):
        collaborators = build_default_order_collaborators()
        self.utils = collaborators.utils
        self.capital_budget = collaborators.capital_budget
        self.delisting_protection = collaborators.delisting_protection
        self.exchange = collaborators.exchange
        self.monitoring = collaborators.monitoring
        self.placement_workflow = collaborators.placement_workflow
        self.placement_intents = self.placement_workflow.intents
        self.trades = collaborators.trades
        self.routing = OrderLifecycleRouting(
            trades=self.trades,
            placement_intents=self.placement_intents,
        )
        self.dca = DcaOrderLifecycle(
            exchange=self.exchange,
            trades=self.trades,
            monitoring=self.monitoring,
            capital_budget=self.capital_budget,
            delisting_protection=self.delisting_protection,
            utils=self.utils,
            placement_workflow=self.placement_workflow,
            routing=self.routing,
            reconciler_factory=lambda: self._build_placement_reconciler(),
        )
        self.accumulation_recovery: RecoverAccumulation | None = None

    async def close(self) -> None:
        """Close exchange resources owned by this order service."""
        await self.exchange.close()

    async def reconcile_placement_intents(
        self,
        config: dict,
    ) -> PlacementReconciliationSummary:
        """Reconcile durable exchange effects before runtime producers start."""
        reconciler = self._build_placement_reconciler()
        try:
            return await reconciler.reconcile(config)
        finally:
            await self.exchange.close()

    def _build_placement_reconciler(self) -> PlacementReconciler:
        """Build recovery callbacks for startup and accepted runtime buys."""
        recovery = PlacementRecoveryHandler(
            exchange=self.exchange,
            trades=self.trades,
            validate_buy=has_valid_buy_fill,
            validate_sell=is_sold_check_status,
            finalize_buy=lambda status, config, **kwargs: finalize_buy_order(
                status,
                config,
                dependencies=self.dca.finalization,
                **kwargs,
            ),
            finalize_sell=lambda status, config, **kwargs: finalize_completed_sell(
                status,
                config,
                dependencies=self.dca.finalization,
                **kwargs,
            ),
            build_limit_sell_payload=lambda trades, evidence: (
                build_tp_limit_sell_payload(
                    trades,
                    evidence,
                    dependencies=self.dca.finalization,
                )
            ),
            persist_limit_fallback=lambda limit_status, config, operation_id: (
                persist_reconciled_limit_fallback(
                    limit_status,
                    config,
                    operation_id,
                    dependencies=self.dca.finalization,
                )
            ),
        )
        return PlacementReconciler(
            self.exchange,
            recovery.resume,
            self.placement_intents,
            accumulation_recovery=self.accumulation_recovery,
        )

    def build_placement_repair(self) -> PlacementRepairService:
        """Build the operator repair service over the shared recovery path."""
        return PlacementRepairService(
            exchange=self.exchange,
            intents=self.placement_intents,
            resume_placement=self._build_placement_reconciler().resume_placement,
        )

    async def arm_tp_limit_order(self, order: dict, config: dict) -> bool:
        """Place and persist a proactive TP limit sell order."""
        return await self.dca.arm_tp_limit_order(order, config)

    async def cancel_tp_limit_order(
        self,
        symbol: str,
        config: dict,
        *,
        expected_snapshot=None,
    ) -> bool:
        """Cancel a persisted proactive TP limit order if one exists."""
        return await self.dca.cancel_tp_limit_order(
            symbol,
            config,
            expected_snapshot=expected_snapshot,
        )

    async def cancel_tp_limit_order_prelocked(
        self,
        symbol: str,
        config: dict,
        *,
        expected_snapshot=None,
    ) -> bool:
        """Cancel a proactive TP order while the caller owns the symbol lock."""
        return await self.dca.cancel_tp_limit_order_prelocked(
            symbol,
            config,
            expected_snapshot=expected_snapshot,
        )

    async def reconcile_tp_limit_order(
        self,
        trades: dict,
        config: dict,
        *,
        expected_snapshot=None,
    ) -> bool:
        """Close the trade if its proactive TP limit order filled."""
        return await self.dca.reconcile_tp_limit_order(
            trades,
            config,
            expected_snapshot=expected_snapshot,
        )

    async def receive_buy_order(self, order, config: dict) -> bool:
        """Create a buy order and persist open trades."""
        return await self.dca.receive_buy_order(order, config)

    async def receive_buy_order_prelocked(self, order, config: dict) -> bool:
        """Execute a buy while the caller owns the symbol lifecycle lock."""
        return await self.dca.receive_buy_order_prelocked(order, config)

    async def receive_sell_order(self, order, config: dict) -> bool:
        """Create a sell order and persist closed trades."""
        return await self.dca.receive_sell_order(order, config)

    async def receive_manual_buy_add(
        self,
        symbol: str,
        date_input,
        price_raw,
        amount_raw,
        config: dict,
    ) -> dict:
        """Append a manual buy as a safety-order row without exchange execution."""
        return await self.dca.receive_manual_buy_add(
            symbol,
            date_input,
            price_raw,
            amount_raw,
            config,
        )

    async def receive_stop_signal(
        self,
        symbol: str,
        config: dict | None = None,
        *,
        expected_snapshot=None,
    ) -> bool:
        """Stop trading for a symbol."""
        return await self.dca.receive_stop_signal(
            symbol,
            config,
            expected_snapshot=expected_snapshot,
        )

    async def receive_stop_signal_result(
        self,
        symbol: str,
        config: dict,
        *,
        operation_id: str | None = None,
    ):
        """Stop a trade and return an explicit operator-visible outcome."""
        return await self.dca.receive_stop_signal_result(
            symbol,
            config,
            operation_id=operation_id,
        )

    async def receive_buy_signal(
        self, symbol: str, ordersize: float, config: dict
    ) -> bool:
        """Handle a manual buy signal."""
        return await self.dca.receive_buy_signal(symbol, ordersize, config)

    async def receive_buy_signal_result(
        self,
        symbol: str,
        ordersize: float,
        config: dict,
        *,
        operation_id: str | None = None,
    ):
        """Handle a manual safety buy and report its durable outcome."""
        return await self.dca.receive_buy_signal_result(
            symbol,
            ordersize,
            config,
            operation_id=operation_id,
        )

    async def receive_sell_signal(self, symbol: str, config: dict) -> bool:
        """Handle a manual sell signal."""
        return await self.dca.receive_sell_signal(symbol, config)

    async def receive_sell_signal_result(
        self,
        symbol: str,
        config: dict,
        *,
        operation_id: str | None = None,
    ):
        """Handle a manual sell and report its durable execution outcome."""
        return await self.dca.receive_sell_signal_result(
            symbol,
            config,
            operation_id=operation_id,
        )
