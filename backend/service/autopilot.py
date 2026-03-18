"""Autopilot trading mode decision logic."""

from typing import Any

import helper
import model
from service.green_phase import GreenPhaseService

logging = helper.LoggerFactory.get_logger("logs/autopilot.log", "autopilot")


class Autopilot:
    """Compute dynamic trading settings based on locked funds."""

    def __init__(self) -> None:
        """Initialize runtime caches."""
        Autopilot.threshold_percent = None
        Autopilot.mode = None
        self.green_phase_service: GreenPhaseService | None = None

    async def _get_green_phase_service(self) -> GreenPhaseService:
        """Return the shared Green Phase service instance."""
        if self.green_phase_service is None:
            self.green_phase_service = await GreenPhaseService.instance()
        return self.green_phase_service

    async def _persist_mode(self, autopilot_mode: str) -> None:
        """Persist the current autopilot mode when it changes."""
        if autopilot_mode == Autopilot.mode:
            return
        Autopilot.mode = autopilot_mode
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
            "tp": None,
            "sl": None,
            "sl_timeout": 0,
            "uses_risk_overrides": False,
        }

    async def resolve_runtime_state(
        self, funds_locked: float, config: dict[str, Any]
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

        if threshold_percent != Autopilot.threshold_percent:
            Autopilot.threshold_percent = threshold_percent
            logging.debug(
                "we reached autopilot %s values - threshold: %s%%",
                autopilot_mode,
                threshold_percent,
            )

        await self._persist_mode(autopilot_mode)
        return runtime_state

    async def calculate_trading_settings(
        self, funds_locked: float, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Return trading settings based on locked funds and thresholds."""
        runtime_state = await self.resolve_runtime_state(funds_locked, config)
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
