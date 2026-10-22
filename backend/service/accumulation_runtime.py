"""Single-owner accumulation orchestration for the application lifespan.

Events coalesce by symbol; timers only advance candle boundaries, collection
rounds and unresolved-order recovery. A WAIT does not enqueue itself again.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import ccxt.async_support as ccxt
import model
from service.accumulation_budget import usable_accumulation_quote
from service.accumulation_commands import (
    AccumulationAction,
    AccumulationCommand,
    AccumulationCommandResult,
)
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_entry import AccumulationEntryService
from service.accumulation_evaluation import evaluate_accumulation
from service.accumulation_exchange import (
    AccumulationExchangeAdapter,
    accumulation_account_scope,
)
from service.accumulation_execution import AccumulationBuyExecutor
from service.accumulation_lifecycle import AccumulationLifecycleService
from service.accumulation_notifications import accumulation_input_notifications
from service.accumulation_portfolio import AccumulationPortfolioCoordinator
from service.accumulation_recovery import AccumulationPlacementRecovery
from service.accumulation_repair import AccumulationOrderRepair
from service.accumulation_sales import AccumulationCommandExecutor
from service.accumulation_state import load_accumulation_context
from service.accumulation_status_events import AccumulationStatusEvents
from service.accumulation_strategy import AccumulationParameters
from service.lifecycle_mutation import lifecycle_mutation_coordinator
from service.order_requests import normalize_order_symbol
from service.strategy_runtime import load_accumulation_strategy_version
from service.trading_controls import is_global_trading_paused
from service.trading_maintenance import trading_maintenance_barrier

# Source-owned capability: editable config and restored rows cannot override it.
ACCUMULATION_RUNTIME_AVAILABLE = True
_EXPECTED_FAILURES = (AccumulationStateError, ccxt.BaseError, TimeoutError, OSError)


def build_accumulation_runtime(
    config_provider: Callable[[], dict[str, Any]],
) -> AccumulationRuntime | None:
    """Keep the production gate independent of editable config and database rows."""
    if not ACCUMULATION_RUNTIME_AVAILABLE:
        return None
    return AccumulationRuntime(AccumulationExchangeAdapter(config_provider))


class AccumulationRuntime:
    """Own one adapter, scheduler and all accumulation work for one lifespan."""

    def __init__(self, adapter: AccumulationExchangeAdapter) -> None:
        self.adapter = adapter
        self.recovery = AccumulationPlacementRecovery(
            adapter.exchange, adapter.account_scope
        )
        self.lifecycle = AccumulationLifecycleService(adapter.readiness)
        self.buys = AccumulationBuyExecutor(adapter)
        self.commands = AccumulationCommandExecutor(adapter)
        self.repairs = AccumulationOrderRepair(adapter)
        self._config: dict[str, Any] | None = None
        self._portfolio: AccumulationPortfolioCoordinator | None = None
        self._dirty: set[str] = set()
        self._all_dirty = True
        self._wake = asyncio.Event()
        self._tick_lock = asyncio.Lock()
        self._running = False
        self._started = False
        self._repair_only = False
        self._input_symbols: set[str] = set()
        self._performance_lock = asyncio.Lock()
        self._performance_cache: dict[str, Any] | None = None
        self._performance_cache_until_ms = 0
        self._next_input_wake_ms = 0
        self._stopping = False
        self._last_recovery_ms: int | None = None
        self._candle_closes: dict[str, int] = {}
        self._rebased: set[str] = set()
        self._seen_retries: set[tuple[str, int]] = set()
        self.status: dict[str, str] = {}
        self.wait_conditions: dict[str, dict[str, Any]] = {}
        self.status_events = AccumulationStatusEvents()
        self._status_fingerprint: str | None = None
        self.entry = AccumulationEntryService(adapter, self.notify)

    @property
    def ready(self) -> bool:
        """Whether this lifespan has completed startup and still accepts requests."""
        return self._started and not self._stopping

    @property
    def repair_ready(self) -> bool:
        """Allow explicit repair reads/writes without admitting a trading worker."""
        return (self._started or self._repair_only) and not self._stopping

    @property
    def current_account_scope(self) -> str | None:
        """Compare credentials for status without authenticating or exposing them."""
        try:
            return accumulation_account_scope(self.adapter.config())
        except AccumulationStateError:
            return None

    async def submit_command(
        self, payload: dict[str, Any]
    ) -> AccumulationCommandResult:
        """Journal operator intent; the worker owns cancellation and sale execution."""
        if not self.ready:
            raise AccumulationStateError("Accumulation runtime is unavailable.")
        command = AccumulationCommand.from_dict(payload)
        if command.action == AccumulationAction.SWITCH_STRATEGY:
            assert command.target_version_id is not None
            await load_accumulation_strategy_version(command.target_version_id)
        scope = await self.adapter.account_scope(self.adapter.config())
        result = await self.lifecycle.submit(payload, account_scope=scope)
        self.notify(normalize_order_symbol(payload["symbol"]))
        return result

    def notify(self, symbol: str | None = None) -> None:
        """Coalesce changed candle, wallet, quote or lifecycle inputs on this loop."""
        if self._stopping:
            return
        self._performance_cache_until_ms = 0
        if symbol is None or len(self._dirty) >= 256:
            self._all_dirty = True
            self._dirty.clear()
        elif not self._all_dirty:
            self._dirty.add(symbol)
        self._wake.set()

    async def performance(self) -> dict[str, Any]:
        """Share one short-lived read-only valuation across dashboard clients."""
        from service.accumulation_performance import accumulation_performance

        async with self._performance_lock:
            if (
                self._performance_cache is not None
                and self.adapter.clock_ms() < self._performance_cache_until_ms
            ):
                return self._performance_cache
            self._performance_cache = await accumulation_performance(self.adapter)
            self._performance_cache_until_ms = min(
                self.adapter.clock_ms() + 2000,
                self._performance_cache["valid_until_ms"],
            )
            return self._performance_cache

    def notify_inputs(self, symbol: str | None = None) -> None:
        """Coalesce market hints without fetching evidence or adding buy cooldowns."""
        if not self.ready or symbol is not None and symbol not in self._input_symbols:
            return
        if symbol is None:
            self._performance_cache_until_ms = 0
        if symbol is None or len(self._dirty) >= 256:
            self._all_dirty = True
            self._dirty.clear()
        elif not self._all_dirty:
            self._dirty.add(symbol)
        now = self.adapter.clock_ms()
        if now >= self._next_input_wake_ms:
            self._next_input_wake_ms = now + 5000
            self._wake.set()

    def _refresh_config(self) -> dict[str, Any]:
        config = self.adapter.config()
        if config != self._config:
            # A round prepared against older settings must not retain old offers.
            self._portfolio = AccumulationPortfolioCoordinator(
                config, self.adapter.admission_inputs, clock_ms=self.adapter.clock_ms
            )
            self._config = config
            self.notify()
        return config

    async def startup(self) -> bool:
        """Recover first and establish new baselines without trading missed bars."""
        if self._started or self._repair_only or self._running or self._stopping:
            raise RuntimeError("Accumulation runtime startup may run only once.")
        rows = await model.AccumulationActivation.all().order_by("symbol")
        if (
            self.adapter.config_provider().get("trade_mode") != "accumulation"
            and not rows
        ):
            self._started = True
            self.status["*"] = "WAIT_ACCUMULATION_MODE"
            return True
        try:
            config = self._refresh_config()
        except AccumulationStateError:
            if self.adapter.config_provider().get("dry_run", True) is not True:
                raise
            # An incomplete demo draft can still serve configuration and repair.
            config = dict(self.adapter.config_provider())
            self.status["*"] = "WAIT_ACCOUNT"
        self._input_symbols = {row.symbol for row in rows}
        for activation in rows:
            await self._recover_symbol(activation, config)
        unresolved = await model.PlacementIntent.filter(
            symbol__in=[row.symbol for row in rows]
        ).exclude(state__in=["completed", "rejected"])
        if unresolved:
            # Recovery may serve HTTP only when every unresolved exchange intent
            # belongs to paused accumulation ownership. Mixed/unknown DCA work
            # keeps the existing fatal startup gate. No producer runs here.
            all_unresolved = await model.PlacementIntent.all().exclude(
                state__in=["completed", "rejected"]
            )
            paused = {row.symbol for row in rows if row.explicitly_paused}
            self._repair_only = all(
                row.symbol in paused
                and row.state in {"quarantined", "restored_quarantined"}
                for row in all_unresolved
            )
            return False
        self._started = True
        if self._config is None:
            return True
        for activation in rows:
            if (
                config.get("trade_mode") == "accumulation"
                and activation.state == "enabled"
                and not activation.explicitly_paused
            ):
                await self._rebase(activation)
        self.notify()
        return True

    async def _rebase(self, activation: model.AccumulationActivation) -> bool:
        try:
            await self.lifecycle.rebase_enabled(
                str(activation.id),
                account_scope=await self.adapter.account_scope(self.adapter.config()),
            )
        except _EXPECTED_FAILURES:
            self.status[activation.symbol] = "WAIT_REBASE"
            return False
        self._rebased.add(str(activation.id))
        self.status[activation.symbol] = "REBASED"
        return True

    async def _recover_symbol(
        self, activation: model.AccumulationActivation, config: dict[str, Any]
    ) -> bool:
        before = activation.revision
        pending = await model.PlacementIntent.filter(symbol=activation.symbol).exclude(
            state__in=["completed", "rejected"]
        )
        changed = False
        for row in pending:
            if row.state in {"quarantined", "restored_quarantined"}:
                self.status[activation.symbol] = "WAIT_REPAIR"
                continue
            try:
                async with asyncio.timeout(10):
                    outcome = await self.recovery.reconcile(row, config)
                changed = changed or outcome != row.state
                await row.refresh_from_db()
                if row.side == "buy" and row.state not in {"completed", "rejected"}:
                    await self._expire_buy(row, config)
            except _EXPECTED_FAILURES:
                self.status[activation.symbol] = "WAIT_RECONCILIATION"
        await activation.refresh_from_db()
        return changed or activation.revision != before

    async def _expire_buy(
        self, row: model.PlacementIntent, config: dict[str, Any]
    ) -> None:
        async with lifecycle_mutation_coordinator.mutation(row.symbol) as admitted:
            if not admitted:
                return
            attempt = await model.AccumulationAttempt.get_or_none(placement_id=row.id)
            if attempt is None:
                raise AccumulationStateError("Expiry cannot cancel an unowned order.")
            opportunity = await model.AccumulationOpportunity.get(
                id=attempt.opportunity_id
            )
            activation = await model.AccumulationActivation.get(
                id=opportunity.activation_id
            )
            scope = await self.adapter.account_scope(config)
            if (
                activation.symbol != row.symbol
                or activation.account_scope != scope
                or row.exchange_name != config["exchange"]
            ):
                raise AccumulationStateError("Expiry order ownership changed.")
            if self.adapter.clock_ms() < opportunity.expires_at_ms:
                return
            await row.refresh_from_db()
            checkpoint = await model.AccumulationFillCheckpoint.get_or_none(
                placement_id=row.id
            )
            if (
                row.state in {"completed", "rejected"}
                or checkpoint is None
                or checkpoint.terminal
                or not row.exchange_order_id
            ):
                return
            row.reason_code = "accumulation_expiry_cancel_requested"
            await row.save(update_fields=["reason_code", "updated_at"])
            async with asyncio.timeout(10):
                await self.adapter.exchange.cancel_spot_order(
                    row.symbol, row.exchange_order_id, config
                )
        async with asyncio.timeout(10):
            await self.recovery.reconcile(
                await self.buys.intents.get(row.operation_id), config
            )

    async def _evaluate(
        self, activation: model.AccumulationActivation, config: dict[str, Any]
    ) -> None:
        self.wait_conditions.pop(activation.symbol, None)
        if is_global_trading_paused(config):
            self.status[activation.symbol] = "WAIT_GLOBAL_PAUSE"
            return
        if (
            config.get("trade_mode") != "accumulation"
            or activation.state != "enabled"
            or activation.explicitly_paused
        ):
            return
        if activation.account_scope != await self.adapter.account_scope(config):
            self.status[activation.symbol] = "WAIT_ACCOUNT"
            return
        if str(activation.id) not in self._rebased:
            await self._rebase(activation)
            return
        try:
            context = await load_accumulation_context(
                str(activation.id), await self.adapter.account_scope(config)
            )
            version = await load_accumulation_strategy_version(
                context.identity.strategy_version_id
            )
            candles = await self.adapter.candles(activation.symbol, version.parameters)
            priority = (
                candles
                if version.parameters == AccumulationParameters()
                else await self.adapter.candles(
                    activation.symbol, AccumulationParameters()
                )
            )
            inputs = await self.adapter.read_inputs(activation.symbol, config)
            usable = await usable_accumulation_quote(
                config, inputs.funding, now_ms=self.adapter.clock_ms()
            )
            decision = await evaluate_accumulation(
                context.identity,
                candles,
                priority_candles=priority,
                now_ms=self.adapter.clock_ms(),
                usable_quote=usable,
                ask_price=inputs.ask_price,
                quote_timestamp_ms=inputs.quote_timestamp_ms,
                minimum_quote=inputs.minimum_quote,
            )
            self.status[activation.symbol] = decision.reason
            if decision.wait_condition is not None:
                self.wait_conditions[activation.symbol] = {
                    **decision.wait_condition,
                    "activation_id": decision.identity.activation_id,
                    "revision": decision.identity.revision,
                    "strategy_version_id": decision.identity.strategy_version_id,
                }
            if decision.reason == "WAIT_REBASE":
                await self._rebase(activation)
            elif decision.action == "BUY":
                assert self._portfolio is not None
                self._portfolio.offer(decision, priority)
        except _EXPECTED_FAILURES:
            self.status[activation.symbol] = "WAIT_DATA"

    async def _retry_due(self, now: int) -> set[str]:
        dirty: set[str] = set()
        seen: set[tuple[str, int]] = set()
        for opportunity in await model.AccumulationOpportunity.filter(
            status="retryable", expires_at_ms__gt=now
        ):
            if opportunity.next_retry_at is None:
                continue
            due = int(opportunity.next_retry_at.timestamp() * 1000)
            key = (str(opportunity.id), due)
            seen.add(key)
            if due > now or key in self._seen_retries:
                continue
            self._seen_retries.add(key)
            attempt = (
                await model.AccumulationAttempt.filter(opportunity=opportunity)
                .order_by("-id")
                .first()
            )
            placement = (
                await model.PlacementIntent.get(id=attempt.placement_id)
                if attempt
                else None
            )
            # Local precision/budget rejection is not a transient wire failure.
            # It waits for changed inputs, rather than spinning on retry timers.
            if placement is not None and placement.state == "completed":
                activation = await model.AccumulationActivation.get(
                    id=opportunity.activation_id
                )
                dirty.add(activation.symbol)
        self._seen_retries.intersection_update(seen)
        return dirty

    async def publish_status(self) -> None:
        """Push only changed public state, shared across all dashboard clients."""
        if not self.status_events.connected:
            self._status_fingerprint = None
            return
        rows = (
            await model.AccumulationActivation.all()
            .order_by("symbol")
            .values("id", "symbol", "revision")
        )
        fingerprint = json.dumps(
            [
                rows,
                self.status,
                self.wait_conditions,
                self.current_account_scope if rows else None,
            ],
            sort_keys=True,
            default=str,
        )
        if fingerprint != self._status_fingerprint:
            self._status_fingerprint = fingerprint
            self.status_events.publish()

    async def tick(self) -> None:
        """Publish after a completed round; dashboard clients never drive trading."""
        await self._tick()
        if self._started and not self._stopping:
            await self.publish_status()

    async def _tick(self) -> None:
        """Run one serialized bounded round; unexpected failures reach supervision."""
        if not self._started or self._stopping:
            return
        async with self._tick_lock, trading_maintenance_barrier.operation() as admitted:
            if not admitted or self._stopping:
                return
            if (
                self.adapter.config_provider().get("trade_mode") != "accumulation"
                and not await model.AccumulationActivation.all().exists()
            ):
                self.status["*"] = "WAIT_ACCUMULATION_MODE"
                return
            try:
                config = self._refresh_config()
            except AccumulationStateError:
                self._portfolio = None
                self._config = None
                self.status["*"] = "WAIT_ACCOUNT"
                return
            rows = await model.AccumulationActivation.all().order_by("symbol")
            symbols = {row.symbol for row in rows}
            self._input_symbols = symbols
            dirty = symbols if self._all_dirty else self._dirty & symbols
            self._all_dirty = False
            self._dirty = set()
            now = self.adapter.clock_ms()
            dirty |= await self._retry_due(now)
            recover = (
                self._last_recovery_ms is None or now - self._last_recovery_ms >= 5000
            )
            if recover:
                self._last_recovery_ms = now
            self.status = {
                symbol: reason
                for symbol, reason in self.status.items()
                if symbol in symbols
            }
            self._candle_closes = {
                symbol: close
                for symbol, close in self._candle_closes.items()
                if symbol in symbols
            }
            self._rebased.intersection_update(str(row.id) for row in rows)
            for activation in rows:
                if self._stopping:
                    return
                if recover and await self._recover_symbol(activation, config):
                    dirty.add(activation.symbol)
                if activation.state == "enabled" and not activation.explicitly_paused:
                    try:
                        version = await load_accumulation_strategy_version(
                            activation.strategy_version_id
                        )
                        close = version.parameters.latest_close(now)
                        if self._candle_closes.get(activation.symbol) != close:
                            dirty.add(activation.symbol)
                            self._candle_closes[activation.symbol] = close
                    except _EXPECTED_FAILURES:
                        self.status[activation.symbol] = "WAIT_STRATEGY"
                        continue
                if activation.symbol not in dirty:
                    continue
                for operation in await model.AccumulationLifecycleOperation.filter(
                    activation=activation, status="pending"
                ).order_by("id"):
                    try:
                        result = await self.commands.execute(operation.operation_id)
                        self.status[activation.symbol] = result.reason
                    except _EXPECTED_FAILURES:
                        self.status[activation.symbol] = "WAIT_COMMAND"
                await activation.refresh_from_db()
                await self._evaluate(activation, config)
            if config.get("trade_mode") != "accumulation":
                self._rebased.clear()
                self._candle_closes.clear()
                self.status["*"] = "WAIT_ACCUMULATION_MODE"
                return
            if self._stopping or self._portfolio is None:
                return
            for admission in await self._portfolio.run_due():
                if admission.operation_id is None:
                    continue
                if self._stopping:
                    return  # Durable prepared placement will be rejected on recovery.
                try:
                    result = await self.buys.execute(admission.operation_id)
                    placement = await self.buys.intents.get(admission.operation_id)
                    self.status[placement.symbol] = result.reason
                except _EXPECTED_FAILURES:
                    self.status["*"] = "WAIT_RECONCILIATION"

    async def run(self) -> None:
        """Run as an application TaskGroup child, never as an unowned background task."""
        if not self._started or self._running or self._stopping:
            raise RuntimeError("Accumulation runtime is not ready to run.")
        accumulation_input_notifications.attach(self, self.notify_inputs)
        self._running = True
        try:
            while not self._stopping:
                self._wake.clear()
                await self.tick()
                if self._stopping:
                    return
                delay = 5.0
                if (
                    self._portfolio is not None
                    and self._portfolio.next_cutoff_ms is not None
                ):
                    delay = min(
                        delay,
                        max(
                            0.001,
                            (self._portfolio.next_cutoff_ms - self.adapter.clock_ms())
                            / 1000,
                        ),
                    )
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
                except TimeoutError:
                    pass
        finally:
            accumulation_input_notifications.detach(self)
            self._running = False

    def request_stop(self) -> None:
        """Stop new admission and wake the loop; never pretend orders were cancelled."""
        self._stopping = True
        self.status_events.close()
        accumulation_input_notifications.detach(self)
        self._wake.set()

    async def shutdown(self) -> None:
        """Close the owned client after the lifespan has joined the runtime task."""
        self.request_stop()
        async with self._tick_lock:
            await self.adapter.close()
