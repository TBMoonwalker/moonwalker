"""Strategy capability checks and supported-strategy filtering."""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

import helper
from service.strategy_builder import BUILTIN_STRATEGY_BY_SLUG
from service.trade_lifecycle_config import TradeLifecycleConfigView

logging = helper.LoggerFactory.get_logger("logs/config.log", "strategy_capability")

HIDDEN_STRATEGY_ALIASES = frozenset({"ema_swing_reverse"})

# Strategy -> indicator methods required by its implementation.
REQUIRED_INDICATOR_METHODS: dict[str, tuple[str, ...]] = {
    "ema_down": ("calculate_ema",),
    "ema20_swing": ("calculate_ema", "get_close_price"),
    "ema20_swing_reverse": ("calculate_ema", "get_close_price"),
    "ema_low": ("calculate_ema", "get_close_price"),
    "ema_swing": ("calculate_ema", "get_close_price"),
    "ema_swing_reverse": ("calculate_ema", "get_close_price"),
    "bollinger_buy": (
        "calculate_bollinger_bands_series",
        "calculate_ema",
        "calculate_rsi_series",
        "get_low_price",
    ),
    "bollinger_sell": (
        "calculate_bollinger_bands_series",
        "calculate_rsi_series",
        "get_high_price",
        "get_close_price",
    ),
}

# Strategy -> minimum closed candles required before the strategy can run safely.
MIN_HISTORY_CANDLES_BY_STRATEGY: dict[str, int] = {
    "ema_down": 200,
    "ema20_swing": 200,
    "ema20_swing_reverse": 200,
    "ema_low": 200,
    "ema_swing": 200,
    "ema_swing_reverse": 200,
    "bollinger_buy": 202,
    "bollinger_sell": 50,
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


def _configured_strategy_names(
    config: dict[str, Any],
    *,
    include_signal_strategy: bool,
) -> list[str | None]:
    """Return configured strategy names for the active lifecycle mode."""
    lifecycle = TradeLifecycleConfigView.from_config(config)
    sidestep_mode = lifecycle.is_sidestep_mode()
    strategy_names: list[str | None] = [config.get("tp_strategy")]

    if sidestep_mode:
        strategy_names.extend(
            [
                lifecycle.bearish_exit_strategy,
                lifecycle.reentry_strategy,
            ]
        )
    else:
        strategy_names.append(config.get("dca_strategy"))

    if include_signal_strategy:
        strategy_names.append(config.get("signal_strategy"))

    return strategy_names


def get_configured_strategy_min_history_candles(
    config: dict[str, Any],
    *,
    include_signal_strategy: bool = True,
) -> int:
    """Return the largest warmup requirement across configured strategies."""
    return max(
        (
            get_strategy_min_history_candles(name)
            for name in _configured_strategy_names(
                config,
                include_signal_strategy=include_signal_strategy,
            )
        ),
        default=0,
    )


def get_configured_strategy_history_lookback_days(
    config: dict[str, Any],
    timeframe: str,
    *,
    include_signal_strategy: bool = True,
    buffer_multiplier: int = 2,
) -> int:
    """Return the largest history lookback needed by configured strategies."""
    return max(
        (
            get_strategy_history_lookback_days(
                name,
                timeframe,
                buffer_multiplier=buffer_multiplier,
            )
            for name in _configured_strategy_names(
                config,
                include_signal_strategy=include_signal_strategy,
            )
        ),
        default=0,
    )


def get_strategy_support_error(strategy_name: str) -> str | None:
    """Return a human-readable support error for a strategy, if any."""
    from service.indicators import Indicators

    normalized_name = str(strategy_name or "").strip()
    builtin = BUILTIN_STRATEGY_BY_SLUG.get(normalized_name)
    required_methods = (
        builtin.required_methods
        if builtin
        else REQUIRED_INDICATOR_METHODS.get(normalized_name, ())
    )
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

    if (
        normalized_name not in BUILTIN_STRATEGY_BY_SLUG
        and not normalized_name.startswith("custom_")
    ):
        return f"Strategy '{strategy_name}' is not registered in Strategy Builder."

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
        if name in HIDDEN_STRATEGY_ALIASES:
            continue
        error = get_strategy_support_error(name)
        if error:
            logging.warning(error)
            continue
        supported.append(name)
    return supported
