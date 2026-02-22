"""Autopilot trading mode decision logic."""

from typing import Any

import helper
import model

logging = helper.LoggerFactory.get_logger("logs/autopilot.log", "autopilot")


class Autopilot:
    """Compute dynamic trading settings based on locked funds."""

    def __init__(self) -> None:

        # Class variables
        Autopilot.threshold_percent = None
        Autopilot.mode = None

    async def calculate_trading_settings(
        self, funds_locked: float, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Return trading settings based on locked funds and thresholds."""
        trading_settings = {}
        if config.get("autopilot", False):
            max_fund = float(config.get("autopilot_max_fund", 0) or 0)
            if max_fund <= 0:
                logging.warning(
                    "Autopilot enabled but autopilot_max_fund is missing/invalid (%s).",
                    config.get("autopilot_max_fund"),
                )
                return trading_settings

            threshold_percent = (funds_locked / max_fund) * 100
            if threshold_percent > 100:
                logging.warning(
                    "Autopilot threshold exceeded 100%% (%.2f%%). "
                    "Funds locked are higher than max_fund.",
                    threshold_percent,
                )

            autopilot_mode = "none"

            if threshold_percent >= float(
                config.get("autopilot_high_threshold", False)
            ):
                autopilot_mode = "high"
                trading_settings["mad"] = int(config.get("autopilot_high_mad", 0))
                trading_settings["tp"] = float(config.get("autopilot_high_tp", 0))
                trading_settings["sl"] = float(config.get("autopilot_high_sl", 0))
                trading_settings["sl_timeout"] = int(
                    config.get("autopilot_high_sl_timeout", 0)
                )
                trading_settings["mode"] = autopilot_mode
            elif threshold_percent >= int(
                config.get("autopilot_medium_threshold", False)
            ):
                autopilot_mode = "medium"
                trading_settings["mad"] = int(config.get("autopilot_medium_mad", 0))
                trading_settings["tp"] = float(config.get("autopilot_medium_tp", 0))
                trading_settings["sl"] = float(config.get("autopilot_medium_sl", 0))
                trading_settings["sl_timeout"] = int(
                    config.get("autopilot_medium_sl_timeout", 0)
                )
                trading_settings["mode"] = autopilot_mode

            if threshold_percent != Autopilot.threshold_percent:
                Autopilot.threshold_percent = threshold_percent
                logging.debug(
                    f"we reached autopilot {autopilot_mode} values - threshold: {threshold_percent}%"
                )
                # Write to DB
                if autopilot_mode != Autopilot.mode:
                    Autopilot.mode = autopilot_mode
                    await model.Autopilot.create(mode=autopilot_mode)

        return trading_settings
