"""Autopilot green-phase detection and guarded deal expansion."""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
from typing import Any

import helper
import model
from service.config import Config
from service.exchange import Exchange
from service.green_phase_logic import (
    analyze_green_phase_rows,
    apply_green_phase_guardrails,
    build_green_phase_override_base,
    build_green_phase_settings,
    build_green_phase_state,
    should_evaluate_green_phase_guardrails,
    to_float,
    to_int,
)

logging = helper.LoggerFactory.get_logger("logs/green_phase.log", "green_phase")
AVAILABLE_QUOTE_UNSET = object()


class GreenPhaseService:
    """Monitor profitable close speed and suggest guarded max-deal boosts."""

    _instance: GreenPhaseService | None = None
    _lock = asyncio.Lock()

    MAX_ANALYSIS_ROWS = 10_000
    MIN_RAMP_TOTAL_CLOSES = 10
    MIN_RAMP_PROFITABLE_CLOSES = 5
    MIN_RECENT_PROFITABLE_CLOSES = 2
    IDLE_LOOP_SECONDS = 5.0

    def __init__(self) -> None:
        """Initialize service state and runtime collaborators."""
        self.config: dict[str, Any] = {}
        self.exchange = Exchange()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._confirm_counter = 0
        self._release_counter = 0
        self._state = self._build_default_state()

    @classmethod
    async def instance(cls) -> "GreenPhaseService":
        """Return the shared Green Phase service instance."""
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                await cls._instance.init()
            return cls._instance

    @staticmethod
    def _build_default_state() -> dict[str, Any]:
        """Return the default in-memory service state."""
        return {
            "enabled": False,
            "ramp_ready": False,
            "green_phase_detected": False,
            "green_phase_active": False,
            "phase_strength": 0.0,
            "baseline_profitable_closes_per_hour": 0.0,
            "recent_profitable_closes_per_hour": 0.0,
            "recent_profitable_close_ratio": 0.0,
            "recent_total_closes": 0,
            "recent_profitable_closes": 0,
            "recommended_extra_deals": 0,
            "effective_extra_deals": 0,
            "effective_max_bots": 0,
            "guardrail_block_reason": None,
            "last_evaluated_at": None,
        }

    async def init(self) -> None:
        """Load config subscription and warm the initial state."""
        config = await Config.instance()
        config.subscribe(self.on_config_change)
        self.on_config_change(config.snapshot())
        await self.refresh_state()

    async def start(self) -> None:
        """Start the continuous monitoring loop."""
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def shutdown(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    def on_config_change(self, config: dict[str, Any]) -> None:
        """Refresh the cached config snapshot."""
        self.config = config

    def get_state(self) -> dict[str, Any]:
        """Return a defensive copy of the latest runtime state."""
        return copy.deepcopy(self._state)

    async def _run_loop(self) -> None:
        """Continuously refresh the speed-detection state."""
        while self._running:
            try:
                await self.refresh_state()
            except Exception as exc:  # noqa: BLE001 - keep runtime loop alive.
                logging.error("Green Phase refresh failed: %s", exc, exc_info=True)

            settings = build_green_phase_settings(self.config)
            interval = settings.eval_interval_seconds
            if not settings.enabled:
                interval = self.IDLE_LOOP_SECONDS
            await asyncio.sleep(interval)

    async def refresh_state(self) -> None:
        """Recompute the raw green-phase detection state from closed trades."""
        settings = build_green_phase_settings(self.config)
        if not settings.enabled:
            self._confirm_counter = 0
            self._release_counter = 0
            self._state = self._build_default_state()
            return

        now = datetime.now(timezone.utc)
        rows = (
            await model.ClosedTrades.all()
            .order_by("-id")
            .limit(self.MAX_ANALYSIS_ROWS)
            .values_list("close_date", "profit")
        )
        analysis, self._confirm_counter, self._release_counter = (
            analyze_green_phase_rows(
                rows,
                now=now,
                settings=settings,
                current_detected=bool(self._state.get("green_phase_detected")),
                confirm_counter=self._confirm_counter,
                release_counter=self._release_counter,
                min_ramp_total_closes=self.MIN_RAMP_TOTAL_CLOSES,
                min_ramp_profitable_closes=self.MIN_RAMP_PROFITABLE_CLOSES,
                min_recent_profitable_closes=self.MIN_RECENT_PROFITABLE_CLOSES,
            )
        )
        self._state = build_green_phase_state(analysis, evaluated_at=now)

    async def get_override(
        self,
        config: dict[str, Any],
        funds_locked: float,
        base_max_bots: int,
        available_quote: float | None | object = AVAILABLE_QUOTE_UNSET,
    ) -> dict[str, Any]:
        """Return the guarded Green Phase max-deal override."""
        state = self.get_state()
        settings = build_green_phase_settings(config)
        result = build_green_phase_override_base(state, base_max_bots=base_max_bots)
        if not should_evaluate_green_phase_guardrails(state, settings):
            return result

        current_reserve = await self._estimate_remaining_open_trade_reserve(config)
        full_trade_budget = self._estimate_full_trade_budget(config)
        if available_quote is AVAILABLE_QUOTE_UNSET:
            available_quote = await self._resolve_available_quote(config, funds_locked)
        else:
            available_quote = self._resolve_available_quote_fallback(
                config=config,
                funds_locked=funds_locked,
                available_quote=available_quote,
            )
        return apply_green_phase_guardrails(
            result,
            settings=settings,
            funds_locked=funds_locked,
            base_max_bots=base_max_bots,
            current_reserve=current_reserve,
            full_trade_budget=full_trade_budget,
            available_quote=available_quote,
        )

    async def _resolve_available_quote(
        self, config: dict[str, Any], funds_locked: float
    ) -> float | None:
        """Return available quote balance for guardrail decisions."""
        currency = str(config.get("currency", "USDC") or "USDC").strip().upper()
        if not currency:
            return None

        available_quote = await self.exchange.get_free_balance_for_asset(
            config, currency
        )
        return self._resolve_available_quote_fallback(
            config=config,
            funds_locked=funds_locked,
            available_quote=available_quote,
        )

    @staticmethod
    def _resolve_available_quote_fallback(
        *,
        config: dict[str, Any],
        funds_locked: float,
        available_quote: float | None,
    ) -> float | None:
        """Normalize an available-quote reading and apply config-based fallback."""
        if available_quote is not None:
            return float(available_quote)

        currency = str(config.get("currency", "USDC") or "USDC").strip().upper()
        if not currency:
            return None

        max_fund = to_float(config.get("autopilot_max_fund"), 0.0)
        if max_fund > 0:
            return max(0.0, max_fund - float(funds_locked or 0.0))
        return None

    async def _estimate_remaining_open_trade_reserve(
        self, config: dict[str, Any]
    ) -> float:
        """Estimate remaining safety-order reserve for already-open trades."""
        open_trades = await model.OpenTrades.all().values("so_count")
        total_reserve = 0.0
        for open_trade in open_trades:
            total_reserve += self._estimate_remaining_trade_reserve(
                config,
                int(open_trade.get("so_count") or 0),
            )
        return round(total_reserve, 8)

    def _estimate_full_trade_budget(self, config: dict[str, Any]) -> float:
        """Estimate full capital budget for a new trade including future SOs."""
        base_order_size = max(0.0, to_float(config.get("bo"), 0.0))
        return round(
            base_order_size + self._estimate_remaining_trade_reserve(config, 0),
            8,
        )

    def _estimate_remaining_trade_reserve(
        self, config: dict[str, Any], so_count: int
    ) -> float:
        """Estimate remaining safety-order reserve for one trade."""
        max_safety_orders = max(0, to_int(config.get("mstc"), 0))
        remaining_orders = max(0, max_safety_orders - max(0, so_count))
        if remaining_orders <= 0:
            return 0.0

        dynamic_dca = bool(config.get("dynamic_dca"))
        base_order_size = max(0.0, to_float(config.get("bo"), 0.0))
        if dynamic_dca:
            return round(base_order_size * remaining_orders, 8)

        safety_order_size = max(0.0, to_float(config.get("so"), 0.0))
        if safety_order_size <= 0:
            return 0.0

        volume_scale = to_float(config.get("os"), 1.0)
        if volume_scale <= 0:
            volume_scale = 1.0

        reserve = 0.0
        for order_index in range(max(0, so_count), max_safety_orders):
            reserve += safety_order_size * (volume_scale**order_index)
        return round(reserve, 8)
