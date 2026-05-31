"""Runtime evaluator for versioned Strategy Builder graphs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import helper
import model
import service.strategy_builder as strategy_builder
import talib
from service.database import run_sqlite_write_with_retry
from service.indicators import Indicators
from tortoise.exceptions import BaseORMException, ConfigurationError

logging = helper.LoggerFactory.get_logger("logs/strategies.log", "strategy_runtime")

EMA20_LOOKBACK_LENGTH = 50
EMA20_REQUIRED_CLOSED_CANDLES = 22


@dataclass
class StrategySnapshot:
    """Cached immutable strategy graph ready for evaluation."""

    slug: str
    version: int
    ir: dict[str, Any]
    validation: dict[str, Any]
    explanation: str


@dataclass
class EvaluationContext:
    """Per-evaluation memoized indicator and state context."""

    slug: str
    timeframe: str
    symbol: str
    side: str
    indicators: Indicators
    candle_index: int | None = None
    state_store: dict[tuple[str, str, str, str], Any] | None = None
    memo: dict[tuple[Any, ...], Any] = field(default_factory=dict)


class GraphStrategyAdapter:
    """Compatibility adapter replacing old Python strategy plugins."""

    def __init__(self, slug: str, timeframe: str) -> None:
        self.slug = slug
        self.timeframe = timeframe
        self.indicators = Indicators()
        self._last_log_by_symbol: dict[str, dict[str, Any]] = {}

    async def run(self, symbol: str, side: str) -> bool:
        """Evaluate the active graph for one symbol."""
        result = await evaluate_strategy_graph(
            self.slug,
            self.timeframe,
            symbol,
            side,
            self.indicators,
        )
        payload = {
            "symbol": symbol,
            "strategy": self.slug,
            "version": result.version,
            "side": side,
            "creating_order": result.matched,
            "reason": result.reason,
        }
        if self._last_log_by_symbol.get(symbol) != payload:
            logging.debug("%s", payload)
            self._last_log_by_symbol[symbol] = payload
        return result.matched


@dataclass(frozen=True)
class StrategyEvaluationResult:
    """Result from evaluating one strategy graph."""

    matched: bool
    version: int | None
    reason: str


_SNAPSHOT_CACHE: dict[str, StrategySnapshot] = {}


def invalidate_strategy_runtime_cache(slug: str | None = None) -> None:
    """Invalidate active graph snapshots after a version promotion."""
    if slug:
        _SNAPSHOT_CACHE.pop(slug, None)
        return
    _SNAPSHOT_CACHE.clear()


async def get_strategy_adapter(slug: str, timeframe: str) -> GraphStrategyAdapter:
    """Return a runtime adapter for DCA, TP, sidestep, and signal paths."""
    snapshot = await _load_strategy_snapshot(slug)
    missing_hooks = _missing_indicator_methods(snapshot.validation)
    if missing_hooks:
        raise ValueError(
            f"Strategy '{slug}' is unavailable because indicator hooks are missing: "
            f"{', '.join(missing_hooks)}."
        )
    return GraphStrategyAdapter(slug, timeframe)


async def evaluate_strategy_graph(
    slug: str,
    timeframe: str,
    symbol: str,
    side: str,
    indicators: Indicators | None = None,
    candle_index: int | None = None,
    state_store: dict[tuple[str, str, str, str], Any] | None = None,
) -> StrategyEvaluationResult:
    """Evaluate a strategy graph against current candle data."""
    snapshot = await _load_strategy_snapshot(slug)
    validation = strategy_builder.validate_strategy_ir(snapshot.ir)
    if validation["status"] != "valid":
        return StrategyEvaluationResult(False, snapshot.version, "invalid_graph")
    missing_hooks = _missing_indicator_methods(validation)
    if missing_hooks:
        return StrategyEvaluationResult(False, snapshot.version, "missing_hooks")

    context = EvaluationContext(
        slug=slug,
        timeframe=timeframe,
        symbol=symbol,
        side=side,
        indicators=indicators or Indicators(),
        candle_index=candle_index,
        state_store=state_store,
    )
    try:
        matched = await _evaluate_root(snapshot.ir, context)
    except Exception as exc:  # noqa: BLE001 - strategy runtime must fail closed.
        logging.error(
            "Cannot evaluate strategy graph %s v%s for %s: %s",
            slug,
            snapshot.version,
            symbol,
            exc,
            exc_info=True,
        )
        return StrategyEvaluationResult(False, snapshot.version, "runtime_error")
    return StrategyEvaluationResult(
        bool(matched), snapshot.version, "matched" if matched else "no_match"
    )


async def _load_strategy_snapshot(slug: str) -> StrategySnapshot:
    """Load and cache the active immutable version for a strategy."""
    cached = _SNAPSHOT_CACHE.get(slug)
    if cached:
        return cached

    detail = await strategy_builder.get_strategy_detail(slug)
    if detail is None:
        raise ValueError(f"Strategy '{slug}' was not found.")
    ir = detail["ir"]
    validation = detail.get("validation") or strategy_builder.validate_strategy_ir(ir)
    snapshot = StrategySnapshot(
        slug=slug,
        version=int(detail.get("active_version") or 0),
        ir=ir,
        validation=validation,
        explanation=str(
            detail.get("explanation")
            or strategy_builder.build_strategy_explanation(ir, validation)
        ),
    )
    _SNAPSHOT_CACHE[slug] = snapshot
    return snapshot


async def _evaluate_root(ir: dict[str, Any], context: EvaluationContext) -> bool:
    """Evaluate the configured root node."""
    root_id = str(ir.get("root") or "")
    nodes = [node for node in ir.get("nodes", []) if isinstance(node, dict)]
    node_by_id = {str(node.get("id")): node for node in nodes}
    root_node = node_by_id.get(root_id)
    if root_node is None:
        return False
    return await _evaluate_node(
        root_node, node_by_id, ir.get("connections", []), context
    )


async def _evaluate_node(
    node: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    connections: Any,
    context: EvaluationContext,
) -> bool:
    """Evaluate one graph node."""
    node_type = str(node.get("type") or "")
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    if node_type == "all":
        input_nodes = _input_nodes_for(node, node_by_id, connections)
        if not input_nodes:
            return False
        ordered_input_nodes = sorted(input_nodes, key=_state_node_sort_key)
        for input_node in ordered_input_nodes:
            if not await _evaluate_node(input_node, node_by_id, connections, context):
                return False
        return True
    if node_type == "any":
        input_nodes = _input_nodes_for(node, node_by_id, connections)
        for input_node in input_nodes:
            if await _evaluate_node(input_node, node_by_id, connections, context):
                return True
        return False
    if node_type in {
        "close_price",
        "low_price",
        "high_price",
        "constant_value",
        "indicator",
    }:
        return False
    if node_type == "comparison":
        return await _evaluate_comparison_node(node, node_by_id, connections, context)
    if node_type == "ema_trend":
        return await _evaluate_ema_trend(params, context)
    if node_type == "price_indicator_relation":
        return await _evaluate_price_indicator_relation(params, context)
    if node_type == "fresh_signal_state":
        return await _evaluate_fresh_signal_state(
            node,
            node_by_id,
            connections,
            context,
        )
    if node_type == "swing_low_state":
        return await _evaluate_swing_low_state(node, node_by_id, connections, context)
    return False


def _input_nodes_for(
    node: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    connections: Any,
) -> list[dict[str, Any]]:
    """Return source nodes connected to a logic node."""
    node_id = str(node.get("id") or "")
    if not isinstance(connections, list):
        return []
    input_nodes: list[dict[str, Any]] = []
    for connection in connections:
        if not isinstance(connection, dict):
            continue
        target = str(connection.get("target") or connection.get("targetNode") or "")
        source = str(connection.get("source") or connection.get("sourceNode") or "")
        if target == node_id and source in node_by_id:
            input_nodes.append(node_by_id[source])
    return input_nodes


def _state_node_sort_key(node: dict[str, Any]) -> bool:
    """Return True for stateful nodes that should run after pure conditions."""
    return str(node.get("type") or "") in {"fresh_signal_state", "swing_low_state"}


async def _evaluate_comparison_node(
    node: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    connections: Any,
    context: EvaluationContext,
) -> bool:
    """Evaluate a graphical comparison node."""
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    value1_node = _input_node_for_port(node, node_by_id, connections, "value1", 0)
    value2_node = _input_node_for_port(node, node_by_id, connections, "value2", 1)
    if value1_node is None or value2_node is None:
        return False
    value1 = await _resolve_value_node(value1_node, context)
    value2 = await _resolve_value_node(value2_node, context)
    if value1 is None or value2 is None:
        return False
    return _compare_values(value1, value2, str(params.get("comparison") or ""))


def _input_node_for_port(
    node: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    connections: Any,
    port: str,
    fallback_index: int,
) -> dict[str, Any] | None:
    """Return an input node for a named port, falling back to connection order."""
    input_nodes = _input_nodes_for(node, node_by_id, connections)
    if not isinstance(connections, list):
        return (
            input_nodes[fallback_index] if len(input_nodes) > fallback_index else None
        )
    node_id = str(node.get("id") or "")
    for connection in connections:
        if not isinstance(connection, dict):
            continue
        target = str(connection.get("target") or connection.get("targetNode") or "")
        target_input = str(
            connection.get("target_input")
            or connection.get("targetInput")
            or connection.get("input")
            or ""
        )
        source = str(connection.get("source") or connection.get("sourceNode") or "")
        if target == node_id and target_input == port and source in node_by_id:
            return node_by_id[source]
    if len(input_nodes) > fallback_index:
        return input_nodes[fallback_index]
    return None


async def _resolve_value_node(
    node: dict[str, Any],
    context: EvaluationContext,
) -> Any:
    """Resolve a data node into its latest comparable value."""
    node_type = str(node.get("type") or "")
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    sample = str(params.get("sample") or "current")
    index_by_sample = {"current": -1, "previous": -2, "two_back": -3}
    index = index_by_sample.get(sample, -1)
    if node_type == "constant_value":
        return params.get("value")
    if node_type == "indicator":
        indicator = str(params.get("indicator") or "")
        if indicator == "ema":
            return await _resolve_ema_value(params, context, index)
        if indicator == "rsi":
            return await _resolve_rsi_indicator(params, context, index)
        if indicator.startswith("bollinger_"):
            return await _resolve_bollinger_indicator(params, context, index)
        if indicator.startswith("macd_"):
            return await _resolve_macd_indicator(params, context, index)
        return None
    if node_type == "close_price":
        lookback = int(params.get("lookback") or EMA20_LOOKBACK_LENGTH)
        close = await _close(context, lookback)
        try:
            value = float(close.dropna().iloc[index])
        except (AttributeError, IndexError, TypeError, ValueError):
            return None
        return None if _is_missing_number(value) else value
    if node_type == "low_price":
        lookback = int(params.get("lookback") or EMA20_LOOKBACK_LENGTH)
        low = await _low(context, lookback)
        try:
            value = float(low.dropna().iloc[index])
        except (AttributeError, IndexError, TypeError, ValueError):
            return None
        return None if _is_missing_number(value) else value
    if node_type == "high_price":
        lookback = int(params.get("lookback") or EMA20_LOOKBACK_LENGTH)
        high = await _high(context, lookback)
        try:
            value = float(high.dropna().iloc[index])
        except (AttributeError, IndexError, TypeError, ValueError):
            return None
        return None if _is_missing_number(value) else value
    return None


async def _resolve_ema_value(
    params: dict[str, Any],
    context: EvaluationContext,
    index: int,
) -> float | None:
    """Resolve an EMA indicator node sample into a comparable value."""
    length = int(params.get("length") or 20)
    ema_series = await _ema_series(
        context,
        length,
        max(length + 2, EMA20_LOOKBACK_LENGTH),
    )
    try:
        value = float(ema_series.iloc[index])
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    return None if _is_missing_number(value) else value


async def _resolve_rsi_indicator(
    params: dict[str, Any],
    context: EvaluationContext,
    index: int,
) -> float | None:
    """Resolve an RSI indicator node sample into a comparable value."""
    length = int(params.get("length") or 14)
    series = await _rsi_series(context, length)
    return _sample_series_value(series, index)


async def _resolve_bollinger_indicator(
    params: dict[str, Any],
    context: EvaluationContext,
    index: int,
) -> float | None:
    """Resolve a Bollinger Band component or bandwidth sample."""
    indicator = str(params.get("indicator") or "")
    component = indicator.removeprefix("bollinger_")
    if component not in {"upper", "middle", "lower", "bandwidth"}:
        return None
    length = int(params.get("length") or 20)
    standard_deviations = float(params.get("standard_deviations") or 2.0)
    series = await _bollinger_series(context, length, standard_deviations)
    if not isinstance(series, dict):
        return None
    return _sample_series_value(series.get(component), index)


async def _resolve_macd_indicator(
    params: dict[str, Any],
    context: EvaluationContext,
    index: int,
) -> float | None:
    """Resolve a MACD line, signal line, or histogram sample."""
    indicator = str(params.get("indicator") or "")
    component = indicator.removeprefix("macd_")
    if component not in {"line", "signal", "histogram"}:
        return None
    component_key = "macd" if component == "line" else component
    fast_period = int(params.get("fast_period") or 12)
    slow_period = int(params.get("slow_period") or 26)
    signal_period = int(params.get("signal_period") or 9)
    series = await _macd_series(
        context,
        fast_period,
        slow_period,
        signal_period,
    )
    if not isinstance(series, dict):
        return None
    return _sample_series_value(series.get(component_key), index)


def _sample_series_value(series: Any, index: int) -> float | None:
    """Return a non-missing numeric value from a sampled indicator series."""
    try:
        value = float(series.iloc[index])
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    return None if _is_missing_number(value) else value


async def _evaluate_fresh_signal_state(
    node: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    connections: Any,
    context: EvaluationContext,
) -> bool:
    """Return true only for a new already-qualified signal state."""
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    direction = str(params.get("direction") or "bullish")
    state_key = str(params.get("state_key") or f"ema20_swing:{direction}")
    latest_close: float | None = None
    latest_indicator: float | None = None

    for input_node in _input_nodes_for(node, node_by_id, connections):
        input_type = str(input_node.get("type") or "")
        input_params = (
            input_node.get("params")
            if isinstance(input_node.get("params"), dict)
            else {}
        )
        value = await _resolve_value_node(input_node, context)
        if value is None:
            continue
        if input_type == "close_price":
            latest_close = value
        elif (
            input_type == "indicator"
            and str(input_params.get("indicator") or "") == "ema"
        ):
            latest_indicator = value

    if latest_close is None or latest_indicator is None:
        return False

    close = await _close(context, EMA20_LOOKBACK_LENGTH)
    ema20_series = await _ema_series(context, 20, EMA20_LOOKBACK_LENGTH)
    try:
        close_series = close.dropna()
        if len(close_series) < EMA20_REQUIRED_CLOSED_CANDLES:
            return False
    except (AttributeError, TypeError):
        return False

    candidate = (latest_close, latest_indicator)
    previous, bootstrapped = await _resolve_tuple_state(
        context,
        state_key,
        bootstrap=lambda: _bootstrap_ema20_state(
            close_series,
            ema20_series,
            direction,
        ),
    )
    result = previous is not None and not bootstrapped and previous != candidate
    if previous != candidate:
        await _remember_state(context, state_key, [latest_close, latest_indicator])
    return result


async def _evaluate_swing_low_state(
    node: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    connections: Any,
    context: EvaluationContext,
) -> bool:
    """Return true when the qualified swing low rises above stored state."""
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    state_key = str(params.get("state_key") or "ema_swing")
    swing_values: list[float] = []
    for input_node in _input_nodes_for(node, node_by_id, connections):
        if str(input_node.get("type") or "") != "close_price":
            continue
        value = await _resolve_value_node(input_node, context)
        if value is not None:
            swing_values.append(float(value))
    if len(swing_values) < 2:
        return False

    current_swing_low = min(swing_values[:2])
    close = await _close(context, 8)
    previous, bootstrapped = await _resolve_float_state(
        context,
        state_key,
        bootstrap=lambda: _bootstrap_ema_swing_state(close),
    )
    result = previous is not None and not bootstrapped and current_swing_low > previous
    if previous != current_swing_low:
        await _remember_state(context, state_key, current_swing_low)
    return result


def _compare_values(left: Any, right: Any, comparison: str) -> bool:
    """Compare two graph operands."""
    if comparison == "less_than":
        return left < right
    if comparison == "greater_or_equal":
        return left >= right
    if comparison == "less_or_equal":
        return left <= right
    if comparison == "not_equals":
        return left != right
    if comparison == "equals":
        return left == right
    return left > right


async def _evaluate_ema_trend(
    params: dict[str, Any], context: EvaluationContext
) -> bool:
    """Compare the latest EMA value with its previous value."""
    length = int(params.get("length") or 20)
    operator = str(params.get("operator") or "greater_than")
    ema_series = await _ema_series(
        context, length, max(length + 2, EMA20_LOOKBACK_LENGTH)
    )
    try:
        latest_value = float(ema_series.iloc[-1])
        previous_value = float(ema_series.iloc[-2])
    except (AttributeError, IndexError, TypeError, ValueError):
        return False
    if _is_missing_number(latest_value) or _is_missing_number(previous_value):
        return False
    if operator == "less_than":
        return latest_value < previous_value
    return latest_value > previous_value


async def _evaluate_price_indicator_relation(
    params: dict[str, Any], context: EvaluationContext
) -> bool:
    """Compare the latest close price with the configured indicator value."""
    indicator = str(params.get("indicator") or "ema")
    length = int(params.get("length") or 20)
    operator = str(params.get("operator") or "greater_than")
    if indicator != "ema":
        return False
    close = await _close(context, max(length + 2, EMA20_LOOKBACK_LENGTH))
    ema_series = await _ema_series(
        context, length, max(length + 2, EMA20_LOOKBACK_LENGTH)
    )
    try:
        close_series = close.dropna()
        close_value = float(close_series.iloc[-1])
        indicator_value = float(ema_series.iloc[-1])
    except (AttributeError, IndexError, TypeError, ValueError):
        return False
    if _is_missing_number(close_value) or _is_missing_number(indicator_value):
        return False
    if operator == "less_than":
        return close_value < indicator_value
    return close_value > indicator_value


async def _close(context: EvaluationContext, length: int) -> Any:
    """Return a memoized close series sliced to the current replay candle."""
    key = ("close", length)
    if key not in context.memo:
        raw = await context.indicators.get_close_price(
            context.symbol, context.timeframe, length
        )
        if context.candle_index is not None and raw is not None:
            raw = _slice_series(raw, context.candle_index)
        context.memo[key] = raw
    return context.memo[key]


async def _low(context: EvaluationContext, length: int) -> Any:
    """Return a memoized low series sliced to the current replay candle."""
    key = ("low", length)
    if key not in context.memo:
        raw = await context.indicators.get_low_price(
            context.symbol, context.timeframe, length
        )
        if context.candle_index is not None and raw is not None:
            raw = _slice_series(raw, context.candle_index)
        context.memo[key] = raw
    return context.memo[key]


async def _high(context: EvaluationContext, length: int) -> Any:
    """Return a memoized high series sliced to the current replay candle."""
    key = ("high", length)
    if key not in context.memo:
        raw = await context.indicators.get_high_price(
            context.symbol, context.timeframe, length
        )
        if context.candle_index is not None and raw is not None:
            raw = _slice_series(raw, context.candle_index)
        context.memo[key] = raw
    return context.memo[key]


async def _ema_series(context: EvaluationContext, length: int, lookback: int) -> Any:
    """Return a memoized EMA series for relation and trend nodes."""
    key = ("ema_series", length, lookback)
    if key not in context.memo:
        try:
            if context.candle_index is not None:
                ema_raw = await context.indicators.calculate_ema_series(
                    context.symbol, context.timeframe, length
                )
                ema_raw = _slice_series(ema_raw, context.candle_index)
            else:
                close = await _close(context, lookback)
                ema_raw = talib.EMA(close.dropna(), timeperiod=length)
            context.memo[key] = ema_raw
        except (AttributeError, TypeError, ValueError):
            context.memo[key] = None
    return context.memo[key]


async def _rsi_series(context: EvaluationContext, length: int) -> Any:
    """Return a memoized RSI series scoped to the replay candle."""
    key = ("rsi_series", length)
    if key not in context.memo:
        raw = await context.indicators.calculate_rsi_series(
            context.symbol,
            context.timeframe,
            length,
        )
        if context.candle_index is not None:
            raw = _slice_series(raw, context.candle_index)
        context.memo[key] = raw
    return context.memo[key]


async def _bollinger_series(
    context: EvaluationContext,
    length: int,
    standard_deviations: float,
) -> dict[str, Any] | None:
    """Return memoized Bollinger series scoped to the replay candle."""
    key = ("bollinger_series", length, standard_deviations)
    if key not in context.memo:
        raw = await context.indicators.calculate_bollinger_bands_series(
            context.symbol,
            context.timeframe,
            length,
            standard_deviations,
        )
        if context.candle_index is not None and isinstance(raw, dict):
            raw = {
                component: _slice_series(series, context.candle_index)
                for component, series in raw.items()
            }
        context.memo[key] = raw
    return context.memo[key]


async def _macd_series(
    context: EvaluationContext,
    fast_period: int,
    slow_period: int,
    signal_period: int,
) -> dict[str, Any] | None:
    """Return memoized MACD series scoped to the replay candle."""
    key = ("macd_series", fast_period, slow_period, signal_period)
    if key not in context.memo:
        raw = await context.indicators.calculate_macd_series(
            context.symbol,
            context.timeframe,
            fast_period,
            slow_period,
            signal_period,
        )
        if context.candle_index is not None and isinstance(raw, dict):
            raw = {
                component: _slice_series(series, context.candle_index)
                for component, series in raw.items()
            }
        context.memo[key] = raw
    return context.memo[key]


async def _memo_indicator(
    context: EvaluationContext, key: tuple[Any, ...], factory: Any
) -> Any:
    """Memoize indicator calls within one graph evaluation."""
    if key not in context.memo:
        context.memo[key] = await factory()
    return context.memo[key]


async def _ema_values_at_candle(
    context: EvaluationContext, lengths: list[int]
) -> dict[str, Any]:
    """Resolve EMA scalar values at the current backtest candle index."""
    values: dict[str, Any] = {}
    for length in lengths:
        series = await context.indicators.calculate_ema_series(
            context.symbol,
            context.timeframe,
            length,
        )
        try:
            value = float(_slice_series(series, context.candle_index or 0).iloc[-1])
        except (AttributeError, IndexError, TypeError, ValueError):
            value = None
        values[f"ema_{length}"] = value
    return values


def _slice_series(series: Any, candle_index: int) -> Any:
    """Slice a pandas Series to only include values up to candle_index.

    When candle_index=0 (first candle), slice to index 0 (inclusive).
    """
    if series is None:
        return None
    end = candle_index + 1
    return series.iloc[:end]


async def _resolve_float_state(
    context: EvaluationContext,
    state_key: str,
    bootstrap: Any,
) -> tuple[float | None, bool]:
    """Resolve a float graph state with optional bootstrap."""
    value = await _load_state(context, state_key)
    if isinstance(value, (int, float)):
        return float(value), False
    bootstrapped = bootstrap()
    if bootstrapped is None:
        return None, False
    await _remember_state(context, state_key, bootstrapped)
    return float(bootstrapped), True


async def _resolve_tuple_state(
    context: EvaluationContext,
    state_key: str,
    bootstrap: Any,
) -> tuple[tuple[float, float] | None, bool]:
    """Resolve a two-float graph state with optional bootstrap."""
    value = await _load_state(context, state_key)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (float(value[0]), float(value[1])), False
    bootstrapped = bootstrap()
    if bootstrapped is None:
        return None, False
    await _remember_state(context, state_key, list(bootstrapped))
    return (float(bootstrapped[0]), float(bootstrapped[1])), True


async def _load_state(context: EvaluationContext, state_key: str) -> Any:
    """Load persisted generic graph state."""
    if context.state_store is not None:
        return context.state_store.get(_state_store_key(context, state_key))

    try:
        row = await model.StrategyGraphState.get_or_none(
            strategy_slug=context.slug,
            state_key=state_key,
            symbol=context.symbol,
            timeframe=context.timeframe,
        )
    except (
        BaseORMException,
        ConfigurationError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        logging.error(
            "Cannot load graph state %s for %s/%s: %s",
            state_key,
            context.slug,
            context.symbol,
            exc,
            exc_info=True,
        )
        return None
    if row is None:
        return None
    try:
        return json.loads(row.value_json)
    except json.JSONDecodeError:
        return None


async def _remember_state(
    context: EvaluationContext, state_key: str, value: Any
) -> None:
    """Persist graph state only when the serialized value changed."""
    if context.state_store is not None:
        context.state_store[_state_store_key(context, state_key)] = value
        return

    value_json = json.dumps(value, sort_keys=True, separators=(",", ":"))
    row = await model.StrategyGraphState.get_or_none(
        strategy_slug=context.slug,
        state_key=state_key,
        symbol=context.symbol,
        timeframe=context.timeframe,
    )
    if row is not None and row.value_json == value_json:
        return

    async def _persist() -> None:
        await model.StrategyGraphState.update_or_create(
            defaults={"value_json": value_json},
            strategy_slug=context.slug,
            state_key=state_key,
            symbol=context.symbol,
            timeframe=context.timeframe,
        )

    await run_sqlite_write_with_retry(
        _persist,
        f"persisting graph state {state_key} for {context.slug}/{context.symbol}",
    )


def _state_store_key(
    context: EvaluationContext, state_key: str
) -> tuple[str, str, str, str]:
    """Return the in-memory state-store key for a strategy state value."""
    return (context.slug, state_key, context.symbol, context.timeframe)


def _bootstrap_ema_swing_state(close: Any) -> float | None:
    """Return latest historical swing low for the current swing-low node."""
    try:
        close_series = close.dropna()
        if len(close_series) < 3:
            return None
        return float(min(close_series.iloc[-2], close_series.iloc[-3]))
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def _bootstrap_ema20_state(
    close_series: Any, ema20_series: Any, direction: str
) -> tuple[float, float] | None:
    """Return latest qualified EMA20 state from candle history."""
    latest_state: tuple[float, float] | None = None
    for idx in range(1, len(close_series)):
        try:
            close_value = float(close_series.iloc[idx])
            ema20_value = float(ema20_series.iloc[idx])
            previous_ema20 = float(ema20_series.iloc[idx - 1])
        except (IndexError, TypeError, ValueError):
            continue
        if _is_missing_number(ema20_value) or _is_missing_number(previous_ema20):
            continue
        if direction == "bearish":
            trigger = ema20_value < previous_ema20 and close_value < ema20_value
        else:
            trigger = ema20_value > previous_ema20 and close_value > ema20_value
        if trigger:
            latest_state = (close_value, ema20_value)
    return latest_state


def _is_missing_number(value: Any) -> bool:
    """Return True for missing or NaN numeric values."""
    return value is None or value != value


def _missing_indicator_methods(validation: dict[str, Any]) -> list[str]:
    """Return unavailable indicator hook names for this runtime."""
    missing: list[str] = []
    for hook in validation.get("hook_readiness", []):
        name = str(hook.get("name") or "")
        if name and not callable(getattr(Indicators, name, None)):
            missing.append(name)
    return missing
