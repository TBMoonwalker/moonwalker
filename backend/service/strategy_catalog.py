"""Static Strategy Builder catalog and node palette."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STRATEGY_IR_SCHEMA_VERSION = 1
STRATEGY_KIND_CUSTOM = "custom"
STRATEGY_KIND_BUILTIN = "builtin"
CUSTOM_SLUG_PREFIX = "custom_"
SUPPORTED_INDICATORS = frozenset(
    {
        "ema",
        "rsi",
        "bollinger_upper",
        "bollinger_middle",
        "bollinger_lower",
        "bollinger_bandwidth",
        "macd_line",
        "macd_signal",
        "macd_histogram",
    }
)


@dataclass(frozen=True)
class BuiltinStrategySpec:
    """Static built-in strategy seed data."""

    slug: str
    name: str
    description: str
    node_type: str
    params: dict[str, Any]
    min_history_candles: int
    required_methods: tuple[str, ...]
    hidden: bool = False


BUILTIN_STRATEGIES: tuple[BuiltinStrategySpec, ...] = (
    BuiltinStrategySpec(
        slug="ema_down",
        name="EMA down",
        description="Checks whether EMA 20 is below EMA 50.",
        node_type="comparison",
        params={"comparison": "less_than"},
        min_history_candles=200,
        required_methods=("calculate_ema",),
    ),
    BuiltinStrategySpec(
        slug="ema20_swing",
        name="EMA20 swing",
        description="Detects a fresh bullish close above a rising EMA20.",
        node_type="all",
        params={"direction": "bullish", "state_key": "ema20_swing:v2"},
        min_history_candles=200,
        required_methods=("calculate_ema", "get_close_price"),
    ),
    BuiltinStrategySpec(
        slug="ema20_swing_reverse",
        name="EMA20 swing reverse",
        description="Detects a fresh bearish close below a falling EMA20.",
        node_type="all",
        params={"direction": "bearish", "state_key": "ema20_swing_reverse:v3"},
        min_history_candles=200,
        required_methods=("calculate_ema", "get_close_price"),
    ),
    BuiltinStrategySpec(
        slug="ema_low",
        name="EMA low rebound",
        description="Requires short EMAs below EMA200 and a close crossing above EMA20.",
        node_type="all",
        params={},
        min_history_candles=200,
        required_methods=("calculate_ema", "get_close_price"),
    ),
    BuiltinStrategySpec(
        slug="ema_swing",
        name="EMA swing",
        description="Tracks higher swing lows while EMA 20/50/100 stay below EMA200.",
        node_type="ema_swing",
        params={"state_key": "ema_swing"},
        min_history_candles=200,
        required_methods=("calculate_ema", "get_close_price"),
    ),
    BuiltinStrategySpec(
        slug="bollinger_buy",
        name="Bollinger Buy",
        description=(
            "Buys a fresh lower-band wick break below the trend-selected EMA, "
            "RSI below 50, and sufficient band width."
        ),
        node_type="all",
        params={},
        min_history_candles=202,
        required_methods=(
            "calculate_bollinger_bands_series",
            "calculate_ema",
            "calculate_rsi_series",
            "get_low_price",
        ),
    ),
)

BUILTIN_STRATEGY_BY_SLUG = {strategy.slug: strategy for strategy in BUILTIN_STRATEGIES}
PUBLIC_BUILTIN_SLUGS = tuple(
    strategy.slug for strategy in BUILTIN_STRATEGIES if not strategy.hidden
)

NODE_PALETTE: tuple[dict[str, Any], ...] = (
    {
        "type": "indicator",
        "label": "Indicator",
        "category": "Indicator",
        "description": "Read a configured indicator value or signal.",
        "params": {"indicator": "ema", "length": 20, "sample": "current"},
        "documentation_url": "/docs/strategies.md#indicator",
    },
    {
        "type": "close_price",
        "label": "Close price",
        "category": "Indicator",
        "description": "Read a current or previous close price.",
        "params": {"lookback": 50, "sample": "current"},
        "documentation_url": "/docs/strategies.md#close-price",
    },
    {
        "type": "low_price",
        "label": "Low price",
        "category": "Indicator",
        "description": "Read a current or previous candle low.",
        "params": {"lookback": 50, "sample": "current"},
        "documentation_url": "/docs/strategies.md#low-price",
    },
    {
        "type": "high_price",
        "label": "High price",
        "category": "Indicator",
        "description": "Read a current or previous candle high.",
        "params": {"lookback": 50, "sample": "current"},
        "documentation_url": "/docs/strategies.md#high-price",
    },
    {
        "type": "constant_value",
        "label": "Constant value",
        "category": "Value",
        "description": "Provide a fixed comparison value.",
        "params": {"value": "up"},
        "documentation_url": "/docs/strategies.md#constant-value",
    },
    {
        "type": "comparison",
        "label": "Comparison",
        "category": "Logic",
        "description": "Compare two connected value nodes.",
        "params": {"comparison": "greater_than"},
        "documentation_url": "/docs/strategies.md#comparison",
    },
    {
        "type": "swing_low_state",
        "label": "Higher swing-low state",
        "category": "State",
        "description": "Compares the qualified swing low with the previous one.",
        "params": {"state_key": "ema_swing"},
        "documentation_url": "/docs/strategies.md#higher-swing-low-state",
    },
    {
        "type": "fresh_signal_state",
        "label": "Fresh signal state",
        "category": "State",
        "description": "Prevents replaying the same qualified signal twice.",
        "params": {"direction": "bullish", "state_key": "ema20_swing:v2"},
        "documentation_url": "/docs/strategies.md#fresh-signal-state",
    },
    {
        "type": "all",
        "label": "All conditions",
        "category": "Logic",
        "description": "Require every input condition.",
        "params": {},
        "documentation_url": "/docs/strategies.md#all-conditions",
    },
    {
        "type": "any",
        "label": "Any condition",
        "category": "Logic",
        "description": "Require at least one input condition.",
        "params": {},
        "documentation_url": "/docs/strategies.md#any-condition",
    },
)
