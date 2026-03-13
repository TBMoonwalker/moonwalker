"""Shared helpers for signal plugin runtime settings and throttling."""

import ast
import json
import time
from dataclasses import dataclass
from typing import Any

import model
from service.autopilot import Autopilot
from service.config import resolve_timeframe
from service.statistic import Statistic


@dataclass(frozen=True)
class CommonSignalRuntime:
    """Parsed runtime settings shared by signal plugins."""

    pair_denylist: list[str] | None
    pair_allowlist: list[str] | None
    volume: dict[str, Any] | None
    strategy_timeframe: str


def parse_signal_settings(raw_value: Any) -> dict[str, Any]:
    """Parse signal settings from config string/dict payloads."""
    if isinstance(raw_value, dict):
        return raw_value
    if raw_value is None:
        return {}

    raw_text = str(raw_value).strip()
    if not raw_text:
        return {}

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        parsed = ast.literal_eval(raw_text)

    if not isinstance(parsed, dict):
        raise TypeError("signal_settings must be a dictionary payload")

    return parsed


def build_common_runtime_settings(config: dict[str, Any]) -> CommonSignalRuntime:
    """Parse common signal runtime settings once per plugin run."""
    pair_denylist = [
        entry.strip().upper().split("/")[0]
        for entry in str(config.get("pair_denylist", "")).split(",")
        if entry.strip()
    ] or None
    pair_allowlist = [
        entry.strip() for entry in str(config.get("pair_allowlist", "")).split(",")
    ] or None
    raw_volume = config.get("volume")
    volume = json.loads(raw_volume) if raw_volume else None
    strategy_timeframe = resolve_timeframe(config)
    return CommonSignalRuntime(
        pair_denylist=pair_denylist,
        pair_allowlist=pair_allowlist,
        volume=volume,
        strategy_timeframe=strategy_timeframe,
    )


def resolve_max_bots_log_interval(
    config: dict[str, Any], default_seconds: float = 60.0
) -> float:
    """Parse and clamp max-bots waiting log interval."""
    try:
        return max(1.0, float(config.get("max_bots_log_interval_sec", default_seconds)))
    except (TypeError, ValueError):
        return default_seconds


def update_waiting_log_state(
    blocked: bool, last_log: float, interval_seconds: float
) -> tuple[bool, float, bool]:
    """Return updated throttling state for max-bots waiting logs."""
    now = time.monotonic()
    should_log = (not blocked) or (now - last_log >= interval_seconds)
    if not should_log:
        return blocked, last_log, False
    return True, now, True


async def is_max_bots_reached(
    config: dict[str, Any],
    statistic: Statistic,
    autopilot: Autopilot,
) -> bool:
    """Return whether the configured max-bot limit currently blocks new trades."""
    max_bots = config.get("max_bots")
    all_bots = await model.Trades.all().distinct().values_list("bot", flat=True)
    profit = await statistic.get_profit()
    if profit["funds_locked"] and profit["funds_locked"] > 0:
        trading_settings = await autopilot.calculate_trading_settings(
            profit["funds_locked"], config
        )
        if trading_settings:
            max_bots = trading_settings["mad"]

    return bool(all_bots) and len(all_bots) >= int(max_bots)
