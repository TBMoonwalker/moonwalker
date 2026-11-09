"""Startup recovery entry for durable exchange placement intents.

Composes a caller-constructed DcaOrderLifecycle with the late-bound
accumulation seam. Owns the startup reconciliation entry point, the
operator placement-repair builder, and the shared exchange close.
"""

from typing import Any

from service.dca.order_lifecycle import DcaOrderLifecycle
from service.placement_reconciliation import (
    PlacementReconciler,
    PlacementReconciliationSummary,
    RecoverAccumulation,
)
from service.placement_repair import PlacementRepairService


class PlacementRecoveryEntry:
    """Start placement reconciliation and build the operator repair service."""

    def __init__(self, *, lifecycle: DcaOrderLifecycle) -> None:
        """Compose the mode-neutral recovery entry over one DCA lifecycle.

        The entry is the documented wiring point for the bybit reconciler
        factory: it must read the accumulation seam at call time so the
        application can bind the seam after construction.
        """
        self.dca = lifecycle
        self.dca.reconciler_factory = self.build_reconciler
        self.accumulation_recovery: RecoverAccumulation | None = None

    def build_reconciler(self) -> PlacementReconciler:
        """Build the recovery reconciler, reading the seam at call time."""
        return PlacementReconciler(
            self.dca.exchange,
            self.dca.build_recovery_handler().resume,
            self.dca.placement_intents,
            accumulation_recovery=self.accumulation_recovery,
        )

    async def reconcile_placement_intents(
        self,
        config: dict[str, Any],
    ) -> PlacementReconciliationSummary:
        """Reconcile durable exchange effects before runtime producers start."""
        reconciler = self.build_reconciler()
        try:
            return await reconciler.reconcile(config)
        finally:
            await self.dca.close()

    def build_placement_repair(self) -> PlacementRepairService:
        """Build the operator repair service over the shared recovery path."""
        return PlacementRepairService(
            exchange=self.dca.exchange,
            intents=self.dca.placement_intents,
            resume_placement=self.build_reconciler().resume_placement,
        )

    async def close(self) -> None:
        """Close exchange resources owned by the composed lifecycle."""
        await self.dca.close()
