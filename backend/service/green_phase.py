"""Autopilot green-phase detection and guarded deal expansion."""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, timezone
from typing import Any

import helper
import model
from service.config import Config
from service.exchange import Exchange
from service.trade_math import parse_date_to_ms

logging = helper.LoggerFactory.get_logger("logs/green_phase.log", "green_phase")


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
        self.on_config_change(config._cache)
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

            interval = self._get_eval_interval_seconds(self.config)
            if not self._is_enabled(self.config):
                interval = self.IDLE_LOOP_SECONDS
            await asyncio.sleep(interval)

    @staticmethod
    def _is_enabled(config: dict[str, Any]) -> bool:
        """Return True when Autopilot and Green Phase are both enabled."""
        return bool(config.get("autopilot")) and bool(
            config.get("autopilot_green_phase_enabled")
        )

    @staticmethod
    def _to_int(value: Any, default: int) -> int:
        """Normalize integer config values with fallback."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        """Normalize float config values with fallback."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _get_eval_interval_seconds(self, config: dict[str, Any]) -> float:
        """Return the configured refresh interval with sane clamping."""
        interval = self._to_float(
            config.get("autopilot_green_phase_eval_interval_sec"),
            60.0,
        )
        return max(5.0, interval)

    def _get_ramp_days(self, config: dict[str, Any]) -> int:
        """Return ramp-up analysis horizon in days."""
        return max(
            1,
            self._to_int(config.get("autopilot_green_phase_ramp_days"), 30),
        )

    def _get_recent_window_minutes(self, config: dict[str, Any]) -> int:
        """Return recent speed window in minutes."""
        return max(
            5,
            self._to_int(config.get("autopilot_green_phase_window_minutes"), 60),
        )

    def _get_confirm_cycles(self, config: dict[str, Any]) -> int:
        """Return the activation hysteresis cycles."""
        return max(
            1,
            self._to_int(config.get("autopilot_green_phase_confirm_cycles"), 2),
        )

    def _get_release_cycles(self, config: dict[str, Any]) -> int:
        """Return the release hysteresis cycles."""
        return max(
            1,
            self._to_int(config.get("autopilot_green_phase_release_cycles"), 4),
        )

    async def refresh_state(self) -> None:
        """Recompute the raw green-phase detection state from closed trades."""
        if not self._is_enabled(self.config):
            self._confirm_counter = 0
            self._release_counter = 0
            self._state = self._build_default_state()
            return

        now = datetime.now(timezone.utc)
        ramp_days = self._get_ramp_days(self.config)
        recent_window_minutes = self._get_recent_window_minutes(self.config)
        ramp_cutoff = now - timedelta(days=ramp_days)
        recent_cutoff = now - timedelta(minutes=recent_window_minutes)

        rows = (
            await model.ClosedTrades.all()
            .order_by("-id")
            .limit(self.MAX_ANALYSIS_ROWS)
            .values_list("close_date", "profit")
        )
        parsed_rows: list[tuple[datetime, float]] = []
        for close_date, profit in rows:
            close_ms = parse_date_to_ms(str(close_date or ""))
            if close_ms is None:
                continue
            close_dt = datetime.fromtimestamp(close_ms / 1000, tz=timezone.utc)
            if close_dt < ramp_cutoff:
                continue
            parsed_rows.append((close_dt, float(profit or 0.0)))

        ramp_total = len(parsed_rows)
        ramp_profitable = sum(1 for _, profit in parsed_rows if profit > 0)
        recent_rows = [
            (close_dt, profit)
            for close_dt, profit in parsed_rows
            if close_dt >= recent_cutoff
        ]
        recent_total = len(recent_rows)
        recent_profitable = sum(1 for _, profit in recent_rows if profit > 0)

        ramp_hours = max(float(ramp_days) * 24.0, 1.0)
        recent_hours = max(float(recent_window_minutes) / 60.0, 1.0 / 12.0)
        baseline_speed = float(ramp_profitable) / ramp_hours
        recent_speed = float(recent_profitable) / recent_hours
        recent_ratio = (
            float(recent_profitable) / float(recent_total) if recent_total > 0 else 0.0
        )
        ramp_ready = (
            ramp_total >= self.MIN_RAMP_TOTAL_CLOSES
            and ramp_profitable >= self.MIN_RAMP_PROFITABLE_CLOSES
            and baseline_speed > 0
        )

        current_active = bool(self._state.get("green_phase_detected"))
        detected = False
        recommended_extra_deals = 0
        phase_strength = 0.0

        if ramp_ready:
            speed_multiplier = self._to_float(
                self.config.get("autopilot_green_phase_speed_multiplier"),
                1.5,
            )
            exit_multiplier = self._to_float(
                self.config.get("autopilot_green_phase_exit_multiplier"),
                1.15,
            )
            min_ratio = self._to_float(
                self.config.get("autopilot_green_phase_min_profitable_close_ratio"),
                0.8,
            )
            max_extra_deals = max(
                0,
                self._to_int(
                    self.config.get("autopilot_green_phase_max_extra_deals"),
                    2,
                ),
            )
            phase_strength = (
                recent_speed / baseline_speed if baseline_speed > 0 else 0.0
            )
            enter_candidate = (
                recent_profitable >= self.MIN_RECENT_PROFITABLE_CLOSES
                and recent_speed >= baseline_speed * max(speed_multiplier, 1.0)
                and recent_ratio >= min_ratio
            )
            exit_candidate = (
                recent_total == 0
                or recent_speed < baseline_speed * max(exit_multiplier, 0.5)
                or recent_ratio < min_ratio
            )

            if current_active:
                self._confirm_counter = 0
                if exit_candidate:
                    self._release_counter += 1
                    if self._release_counter >= self._get_release_cycles(self.config):
                        detected = False
                        self._release_counter = 0
                    else:
                        detected = True
                else:
                    self._release_counter = 0
                    detected = True
            else:
                self._release_counter = 0
                if enter_candidate:
                    self._confirm_counter += 1
                    if self._confirm_counter >= self._get_confirm_cycles(self.config):
                        detected = True
                        self._confirm_counter = 0
                else:
                    self._confirm_counter = 0

            if detected and max_extra_deals > 0:
                recommended_extra_deals = min(
                    max_extra_deals,
                    max(1, int(phase_strength / max(speed_multiplier, 0.1))),
                )
        else:
            self._confirm_counter = 0
            self._release_counter = 0

        self._state = {
            "enabled": True,
            "ramp_ready": ramp_ready,
            "green_phase_detected": detected,
            "green_phase_active": False,
            "phase_strength": round(phase_strength, 4),
            "baseline_profitable_closes_per_hour": round(baseline_speed, 6),
            "recent_profitable_closes_per_hour": round(recent_speed, 6),
            "recent_profitable_close_ratio": round(recent_ratio, 6),
            "recent_total_closes": recent_total,
            "recent_profitable_closes": recent_profitable,
            "recommended_extra_deals": recommended_extra_deals,
            "effective_extra_deals": 0,
            "effective_max_bots": 0,
            "guardrail_block_reason": ("ramp_not_ready" if not ramp_ready else None),
            "last_evaluated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

    async def get_override(
        self,
        config: dict[str, Any],
        funds_locked: float,
        base_max_bots: int,
    ) -> dict[str, Any]:
        """Return the guarded Green Phase max-deal override."""
        state = self.get_state()
        result = {
            **state,
            "green_phase_active": False,
            "effective_extra_deals": 0,
            "effective_max_bots": max(0, int(base_max_bots or 0)),
            "guardrail_block_reason": state.get("guardrail_block_reason"),
        }
        if (
            not self._is_enabled(config)
            or not state["ramp_ready"]
            or not state["green_phase_detected"]
        ):
            return result

        max_extra_deals = min(
            max(0, int(state["recommended_extra_deals"] or 0)),
            max(
                0,
                self._to_int(config.get("autopilot_green_phase_max_extra_deals"), 2),
            ),
        )
        if max_extra_deals <= 0:
            result["guardrail_block_reason"] = "no_extra_deals_configured"
            return result

        current_reserve = await self._estimate_remaining_open_trade_reserve(config)
        full_trade_budget = self._estimate_full_trade_budget(config)
        if full_trade_budget <= 0:
            result["guardrail_block_reason"] = "invalid_trade_budget"
            return result

        available_quote = await self._resolve_available_quote(config, funds_locked)
        if available_quote is None:
            result["guardrail_block_reason"] = "balance_unavailable"
            return result

        max_fund = self._to_float(config.get("autopilot_max_fund"), 0.0)
        max_locked_percent = self._to_float(
            config.get("autopilot_green_phase_max_locked_fund_percent"),
            85.0,
        )
        base_order_size = max(0.0, self._to_float(config.get("bo"), 0.0))
        result["guardrail_block_reason"] = "reserve_shortfall"

        for extra_deals in range(max_extra_deals, 0, -1):
            if max_fund > 0 and base_order_size > 0:
                projected_locked_percent = (
                    (float(funds_locked) + base_order_size * extra_deals) / max_fund
                ) * 100
                if projected_locked_percent > max_locked_percent:
                    result["guardrail_block_reason"] = "locked_fund_guardrail"
                    continue

            required_quote = current_reserve + full_trade_budget * extra_deals
            if available_quote + 1e-12 < required_quote:
                result["guardrail_block_reason"] = "reserve_shortfall"
                continue

            result["green_phase_active"] = True
            result["effective_extra_deals"] = extra_deals
            result["effective_max_bots"] = max(0, int(base_max_bots or 0) + extra_deals)
            result["guardrail_block_reason"] = None
            return result

        return result

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
        if available_quote is not None:
            return float(available_quote)

        max_fund = self._to_float(config.get("autopilot_max_fund"), 0.0)
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
        base_order_size = max(0.0, self._to_float(config.get("bo"), 0.0))
        return round(
            base_order_size + self._estimate_remaining_trade_reserve(config, 0),
            8,
        )

    def _estimate_remaining_trade_reserve(
        self, config: dict[str, Any], so_count: int
    ) -> float:
        """Estimate remaining safety-order reserve for one trade."""
        max_safety_orders = max(0, self._to_int(config.get("mstc"), 0))
        remaining_orders = max(0, max_safety_orders - max(0, so_count))
        if remaining_orders <= 0:
            return 0.0

        dynamic_dca = bool(config.get("dynamic_dca"))
        base_order_size = max(0.0, self._to_float(config.get("bo"), 0.0))
        if dynamic_dca:
            return round(base_order_size * remaining_orders, 8)

        safety_order_size = max(0.0, self._to_float(config.get("so"), 0.0))
        if safety_order_size <= 0:
            return 0.0

        volume_scale = self._to_float(config.get("os"), 1.0)
        if volume_scale <= 0:
            volume_scale = 1.0

        reserve = 0.0
        for order_index in range(max(0, so_count), max_safety_orders):
            reserve += safety_order_size * (volume_scale**order_index)
        return round(reserve, 8)
