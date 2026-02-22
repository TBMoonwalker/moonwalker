"""Strategy capability checks and supported-strategy filtering."""

from __future__ import annotations

import importlib
from typing import Iterable

import helper

logging = helper.LoggerFactory.get_logger("logs/config.log", "strategy_capability")

# Strategy -> indicator methods required by its implementation.
REQUIRED_INDICATOR_METHODS: dict[str, tuple[str, ...]] = {
    "bbands_cross": ("calculate_bbands_cross",),
    "ema_cross": ("calculate_ema_cross",),
    "ema_down": ("calculate_ema",),
    "ema_low": ("calculate_ema", "get_close_price"),
    "ichimoku_cross": ("calculate_ichimoku_cross",),
    "tothemoonv2": (
        "calculate_ema_slope",
        "calculate_rsi_slope",
        "calculate_ema_cross",
    ),
}


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
