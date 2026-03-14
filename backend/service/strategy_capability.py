"""Strategy capability checks and supported-strategy filtering."""

from __future__ import annotations

import importlib
import math
import re
from typing import Any, Iterable

import helper

logging = helper.LoggerFactory.get_logger("logs/config.log", "strategy_capability")

# Strategy -> indicator methods required by its implementation.
REQUIRED_INDICATOR_METHODS: dict[str, tuple[str, ...]] = {
    "bbands_cross": ("calculate_bbands_cross",),
    "ema_cross": ("calculate_ema_cross",),
    "ema_down": ("calculate_ema",),
    "ema_low": ("calculate_ema", "get_close_price"),
    "ema_swing": ("calculate_ema", "get_close_price"),
    "ichimoku_cross": ("calculate_ichimoku_cross",),
    "tothemoonv2": (
        "calculate_ema_slope",
        "calculate_rsi_slope",
        "calculate_ema_cross",
    ),
}

# Strategy -> minimum closed candles required before the strategy can run safely.
MIN_HISTORY_CANDLES_BY_STRATEGY: dict[str, int] = {
    "bbands_cross": 50,
    "ema_cross": 22,
    "ema_down": 200,
    "ema_low": 200,
    "ema_swing": 200,
    "ichimoku_cross": 52,
    "tothemoonv2": 50,
}

_SECONDS_PER_DAY = 24 * 60 * 60


def _timeframe_to_seconds(timeframe: str) -> int:
    """Convert timeframe notation like 1m/1h/4h/1d to seconds."""
    normalized = str(timeframe or "").strip().lower().replace("min", "m")
    match = re.fullmatch(r"(\d+)\s*([mhdw])", normalized)
    if not match:
        return 60

    amount = max(1, int(match.group(1)))
    unit = match.group(2)
    multipliers = {
        "m": 60,
        "h": 60 * 60,
        "d": _SECONDS_PER_DAY,
        "w": 7 * _SECONDS_PER_DAY,
    }
    return amount * multipliers[unit]


def get_strategy_min_history_candles(strategy_name: str | None) -> int:
    """Return the minimum closed-candle warmup count for a strategy."""
    if not strategy_name:
        return 0
    return MIN_HISTORY_CANDLES_BY_STRATEGY.get(str(strategy_name).strip(), 0)


def get_strategy_history_lookback_days(
    strategy_name: str | None,
    timeframe: str,
    *,
    buffer_multiplier: int = 2,
) -> int:
    """Return the minimum history lookback in days needed for a strategy."""
    minimum_candles = get_strategy_min_history_candles(strategy_name)
    if minimum_candles <= 0:
        return 0

    timeframe_seconds = _timeframe_to_seconds(timeframe)
    lookback_seconds = minimum_candles * max(1, buffer_multiplier) * timeframe_seconds
    return max(1, math.ceil(lookback_seconds / _SECONDS_PER_DAY))


def get_configured_strategy_min_history_candles(
    config: dict[str, Any],
    *,
    include_signal_strategy: bool = True,
) -> int:
    """Return the largest warmup requirement across configured strategies."""
    strategy_names: list[str | None] = [
        config.get("dca_strategy"),
        config.get("tp_strategy"),
    ]
    if include_signal_strategy:
        strategy_names.append(config.get("signal_strategy"))

    return max(
        (get_strategy_min_history_candles(name) for name in strategy_names), default=0
    )


def get_configured_strategy_history_lookback_days(
    config: dict[str, Any],
    timeframe: str,
    *,
    include_signal_strategy: bool = True,
    buffer_multiplier: int = 2,
) -> int:
    """Return the largest history lookback needed by configured strategies."""
    strategy_names: list[str | None] = [
        config.get("dca_strategy"),
        config.get("tp_strategy"),
    ]
    if include_signal_strategy:
        strategy_names.append(config.get("signal_strategy"))

    return max(
        (
            get_strategy_history_lookback_days(
                name,
                timeframe,
                buffer_multiplier=buffer_multiplier,
            )
            for name in strategy_names
        ),
        default=0,
    )


def get_strategy_support_error(strategy_name: str) -> str | None:
    """Return a human-readable support error for a strategy, if any."""
    from service.indicators import Indicators

    required_methods = REQUIRED_INDICATOR_METHODS.get(strategy_name, ())
    if required_methods:
        missing = [
            method
            for method in required_methods
            if not callable(getattr(Indicators, method, None))
        ]
        if missing:
            return (
                f"Strategy '{strategy_name}' is not supported because indicator "
                f"methods are missing: {', '.join(missing)}."
            )

    try:
        module = importlib.import_module(f"strategies.{strategy_name}")
    except Exception as exc:
        return f"Strategy '{strategy_name}' cannot be imported: {exc}"

    strategy_class = getattr(module, "Strategy", None)
    if strategy_class is None:
        return f"Strategy '{strategy_name}' is missing class 'Strategy'."

    run_method = getattr(strategy_class, "run", None)
    if not callable(run_method):
        return f"Strategy '{strategy_name}' is missing callable method 'run'."

    return None


def ensure_strategy_supported(strategy_name: str) -> None:
    """Raise ValueError when strategy is not currently supported."""
    error = get_strategy_support_error(strategy_name)
    if error:
        raise ValueError(error)


def filter_supported_strategies(strategy_names: Iterable[str]) -> list[str]:
    """Filter and return only currently supported strategies."""
    supported: list[str] = []
    for name in strategy_names:
        error = get_strategy_support_error(name)
        if error:
            logging.warning(error)
            continue
        supported.append(name)
    return supported
