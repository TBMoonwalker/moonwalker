"""Autopilot trading mode decision logic."""

from dataclasses import dataclass
from typing import Any

import helper
import model
from service.autopilot_memory import AutopilotMemoryService
from service.autopilot_runtime import (
    AutopilotRuntimeState,
    get_shared_autopilot_runtime_state,
)
from service.green_phase import AVAILABLE_QUOTE_UNSET, GreenPhaseService

logging = helper.LoggerFactory.get_logger("logs/autopilot.log", "autopilot")


@dataclass(frozen=True)
class ResolvedTradingPolicy:
    """Resolved per-symbol trading policy for the current ticker cycle."""

    symbol: str
    mode: str
    effective_max_bots: int
    take_profit: float
    baseline_take_profit: float
    stop_loss: float
    stop_loss_timeout: int
    green_phase_active: bool
    green_phase_extra_deals: int
    adaptive_tp_applied: bool
    adaptive_reason_code: str | None
    adaptive_trust_score: float | None
    memory_status: str | None
    suggested_base_order: float | None


class Autopilot:
    """Compute dynamic trading settings based on locked funds."""

    def __init__(
        self,
        runtime_state: AutopilotRuntimeState | None = None,
    ) -> None:
        """Initialize runtime collaborators and dedupe state."""
        self.green_phase_service: GreenPhaseService | None = None
        self.memory_service: AutopilotMemoryService | None = None
        self._runtime_state = (
            runtime_state
            if runtime_state is not None
            else get_shared_autopilot_runtime_state()
        )

    async def _get_green_phase_service(self) -> GreenPhaseService:
        """Return the shared Green Phase service instance."""
        if self.green_phase_service is None:
            self.green_phase_service = await GreenPhaseService.instance()
        return self.green_phase_service

    async def _get_memory_service(self) -> AutopilotMemoryService:
        """Return the shared Autopilot memory service instance."""
        if self.memory_service is None:
            self.memory_service = await AutopilotMemoryService.instance()
        return self.memory_service

    async def _persist_mode(self, autopilot_mode: str) -> None:
        """Persist the current autopilot mode when it changes."""
        if not self._runtime_state.update_mode(autopilot_mode):
            return
        await model.Autopilot.create(mode=autopilot_mode)

    @staticmethod
    def _build_default_runtime_state(
        config: dict[str, Any], autopilot_mode: str = "none"
    ) -> dict[str, Any]:
        """Return the default runtime state payload."""
        base_max_bots = int(config.get("max_bots", 0) or 0)
        return {
            "enabled": bool(config.get("autopilot", False)),
            "mode": autopilot_mode,
            "threshold_percent": 0.0,
            "base_max_bots": base_max_bots,
            "effective_max_bots": base_max_bots,
            "green_phase_detected": False,
            "green_phase_active": False,
            "green_phase_extra_deals": 0,
            "green_phase_strength": 0.0,
            "green_phase_block_reason": None,
            "green_phase_ramp_ready": False,
            "memory_status": "empty",
            "memory_stale": False,
            "memory_stale_reason": None,
            "memory_current_closes": 0,
            "memory_required_closes": 0,
            "memory_featured_symbol": None,
            "memory_featured_direction": None,
            "memory_last_updated_at": None,
            "tp": None,
            "sl": None,
            "sl_timeout": 0,
            "uses_risk_overrides": False,
        }

    async def resolve_runtime_state(
        self,
        funds_locked: float,
        config: dict[str, Any],
        *,
        available_quote: float | None | object = AVAILABLE_QUOTE_UNSET,
    ) -> dict[str, Any]:
        """Return merged Autopilot runtime state including Green Phase."""
        runtime_state = self._build_default_runtime_state(config)
        if not config.get("autopilot", False):
            await self._persist_mode("none")
            return runtime_state

        max_fund = float(config.get("autopilot_max_fund", 0) or 0)
        autopilot_mode = "low"
        threshold_percent = 0.0
        if max_fund <= 0:
            logging.warning(
                "Autopilot enabled but autopilot_max_fund is missing/invalid (%s).",
                config.get("autopilot_max_fund"),
            )
            runtime_state["mode"] = autopilot_mode
            runtime_state["green_phase_block_reason"] = "invalid_autopilot_max_fund"
            await self._persist_mode(autopilot_mode)
            return runtime_state

        threshold_percent = (funds_locked / max_fund) * 100
        if threshold_percent > 100:
            logging.warning(
                "Autopilot threshold exceeded 100%% (%.2f%%). "
                "Funds locked are higher than max_fund.",
                threshold_percent,
            )

        if threshold_percent >= float(config.get("autopilot_high_threshold", False)):
            autopilot_mode = "high"
            runtime_state["base_max_bots"] = int(config.get("autopilot_high_mad", 0))
            runtime_state["effective_max_bots"] = runtime_state["base_max_bots"]
            runtime_state["tp"] = float(config.get("autopilot_high_tp", 0))
            runtime_state["sl"] = float(config.get("autopilot_high_sl", 0))
            runtime_state["sl_timeout"] = int(
                config.get("autopilot_high_sl_timeout", 0)
            )
            runtime_state["uses_risk_overrides"] = True
        elif threshold_percent >= int(config.get("autopilot_medium_threshold", False)):
            autopilot_mode = "medium"
            runtime_state["base_max_bots"] = int(config.get("autopilot_medium_mad", 0))
            runtime_state["effective_max_bots"] = runtime_state["base_max_bots"]
            runtime_state["tp"] = float(config.get("autopilot_medium_tp", 0))
            runtime_state["sl"] = float(config.get("autopilot_medium_sl", 0))
            runtime_state["sl_timeout"] = int(
                config.get("autopilot_medium_sl_timeout", 0)
            )
            runtime_state["uses_risk_overrides"] = True

        green_phase_service = await self._get_green_phase_service()
        green_phase_state = await green_phase_service.get_override(
            config=config,
            funds_locked=funds_locked,
            base_max_bots=int(runtime_state["base_max_bots"] or 0),
            available_quote=available_quote,
        )

        runtime_state["mode"] = autopilot_mode
        runtime_state["threshold_percent"] = threshold_percent
        runtime_state["green_phase_detected"] = bool(
            green_phase_state.get("green_phase_detected")
        )
        runtime_state["green_phase_active"] = bool(
            green_phase_state.get("green_phase_active")
        )
        runtime_state["green_phase_extra_deals"] = int(
            green_phase_state.get("effective_extra_deals") or 0
        )
        runtime_state["green_phase_strength"] = float(
            green_phase_state.get("phase_strength") or 0.0
        )
        runtime_state["green_phase_block_reason"] = green_phase_state.get(
            "guardrail_block_reason"
        )
        runtime_state["green_phase_ramp_ready"] = bool(
            green_phase_state.get("ramp_ready")
        )
        runtime_state["effective_max_bots"] = int(
            green_phase_state.get("effective_max_bots")
            or runtime_state["effective_max_bots"]
        )
        try:
            memory_summary = (await self._get_memory_service()).get_runtime_summary()
        except Exception as exc:  # noqa: BLE001 - fail open to baseline summary.
            logging.warning(
                "Autopilot memory summary unavailable: %s",
                exc,
            )
            memory_summary = {
                "status": "stale",
                "stale": True,
                "stale_reason": "memory_unavailable",
                "current_closes": 0,
                "required_closes": 0,
                "featured_symbol": None,
                "featured_direction": None,
                "last_updated_at": None,
                "last_success_at": None,
            }
        runtime_state["memory_status"] = memory_summary.get("status")
        runtime_state["memory_stale"] = bool(memory_summary.get("stale"))
        runtime_state["memory_stale_reason"] = memory_summary.get("stale_reason")
        runtime_state["memory_current_closes"] = int(
            memory_summary.get("current_closes") or 0
        )
        runtime_state["memory_required_closes"] = int(
            memory_summary.get("required_closes") or 0
        )
        runtime_state["memory_featured_symbol"] = memory_summary.get("featured_symbol")
        runtime_state["memory_featured_direction"] = memory_summary.get(
            "featured_direction"
        )
        runtime_state["memory_last_updated_at"] = memory_summary.get("last_updated_at")

        if self._runtime_state.update_threshold_percent(threshold_percent):
            logging.debug(
                "we reached autopilot %s values - threshold: %s%%",
                autopilot_mode,
                threshold_percent,
            )

        await self._persist_mode(autopilot_mode)
        return runtime_state

    async def calculate_trading_settings(
        self,
        funds_locked: float,
        config: dict[str, Any],
        *,
        available_quote: float | None | object = AVAILABLE_QUOTE_UNSET,
    ) -> dict[str, Any]:
        """Return trading settings based on locked funds and thresholds."""
        runtime_state = await self.resolve_runtime_state(
            funds_locked,
            config,
            available_quote=available_quote,
        )
        if not runtime_state["uses_risk_overrides"]:
            return {}
        return {
            "mad": runtime_state["effective_max_bots"],
            "tp": runtime_state["tp"],
            "sl": runtime_state["sl"],
            "sl_timeout": runtime_state["sl_timeout"],
            "mode": runtime_state["mode"],
            "green_phase_active": runtime_state["green_phase_active"],
            "green_phase_extra_deals": runtime_state["green_phase_extra_deals"],
            "effective_mad": runtime_state["effective_max_bots"],
        }

    async def resolve_trading_policy(
        self,
        symbol: str,
        funds_locked: float,
        config: dict[str, Any],
        *,
        available_quote: float | None | object = AVAILABLE_QUOTE_UNSET,
    ) -> ResolvedTradingPolicy:
        """Return the explicit per-symbol trading policy for one ticker cycle."""
        runtime_state = await self.resolve_runtime_state(
            funds_locked,
            config,
            available_quote=available_quote,
        )
        baseline_take_profit = (
            float(runtime_state["tp"])
            if runtime_state["uses_risk_overrides"] and runtime_state["tp"] is not None
            else float(config.get("tp", 0.0) or 0.0)
        )
        stop_loss = (
            float(runtime_state["sl"])
            if runtime_state["uses_risk_overrides"] and runtime_state["sl"] is not None
            else float(config.get("sl", 0.0) or 0.0)
        )
        stop_loss_timeout = (
            int(runtime_state["sl_timeout"])
            if runtime_state["uses_risk_overrides"]
            else 0
        )
        suggested_base_order = float(config.get("bo", 0.0) or 0.0)
        adaptive_tp_applied = False
        adaptive_reason_code: str | None = None
        adaptive_trust_score: float | None = None

        try:
            memory_policy = (await self._get_memory_service()).resolve_symbol_policy(
                symbol,
                enabled=bool(config.get("autopilot", False)),
                baseline_take_profit=baseline_take_profit,
                base_order_amount=suggested_base_order,
            )
        except Exception as exc:  # noqa: BLE001 - fail open to baseline policy.
            logging.warning(
                "Autopilot memory policy unavailable for %s: %s",
                symbol,
                exc,
            )
            memory_policy = {
                "apply_tp": False,
                "take_profit": baseline_take_profit,
                "suggested_base_order": suggested_base_order,
                "memory_status": "stale",
                "reason_code": "memory_unavailable",
                "trust_score": None,
            }
        take_profit = float(memory_policy["take_profit"])
        suggested_base_order = float(memory_policy["suggested_base_order"] or 0.0)
        adaptive_tp_applied = bool(memory_policy["apply_tp"])
        adaptive_reason_code = memory_policy.get("reason_code")
        adaptive_trust_score = memory_policy.get("trust_score")

        return ResolvedTradingPolicy(
            symbol=symbol,
            mode=str(runtime_state["mode"]),
            effective_max_bots=int(runtime_state["effective_max_bots"] or 0),
            take_profit=take_profit,
            baseline_take_profit=baseline_take_profit,
            stop_loss=stop_loss,
            stop_loss_timeout=stop_loss_timeout,
            green_phase_active=bool(runtime_state["green_phase_active"]),
            green_phase_extra_deals=int(runtime_state["green_phase_extra_deals"] or 0),
            adaptive_tp_applied=adaptive_tp_applied,
            adaptive_reason_code=adaptive_reason_code,
            adaptive_trust_score=adaptive_trust_score,
            memory_status=runtime_state.get("memory_status"),
            suggested_base_order=suggested_base_order,
        )
