"""Build chart indicator series from Strategy Builder graphs."""

from __future__ import annotations

import math
from typing import Any, Protocol

from service.indicators import Indicators

CHART_INDICATOR_STYLES: dict[str, tuple[str, str, str]] = {
    "ema": ("price", "line", "#B7791F"),
    "bollinger_upper": ("price", "line", "#356D86"),
    "bollinger_middle": ("price", "line", "#8A948D"),
    "bollinger_lower": ("price", "line", "#2E7D5B"),
    "bollinger_bandwidth": ("bandwidth", "line", "#356D86"),
    "rsi": ("rsi", "line", "#B7791F"),
    "macd_line": ("macd", "line", "#356D86"),
    "macd_signal": ("macd", "line", "#B7791F"),
    "macd_histogram": ("macd", "histogram", "#8A948D"),
}


class ChartCandle(Protocol):
    """Minimal candle shape required for chart indicator points."""

    timestamp: int


class StrategyChartIndicatorBuilder:
    """Collect strategy graph indicators and build frontend chart series."""

    def __init__(self, symbol: str, timeframe: str) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self._requirements: dict[str, dict[str, Any]] = {}

    async def collect_strategy_requirements(self, *slugs: str) -> list[str]:
        """Load strategy graph snapshots and collect supported indicator series."""
        from service.strategy_runtime import _load_strategy_snapshot as load_snapshot

        loaded: list[str] = []
        for slug in dict.fromkeys(
            str(slug).strip() for slug in slugs if str(slug).strip()
        ):
            try:
                snapshot = await load_snapshot(slug)
            except Exception:  # noqa: BLE001 - one bad strategy must not break charts.
                continue
            ir = getattr(snapshot, "ir", None)
            if isinstance(ir, dict):
                self.collect_ir_requirements(ir)
                loaded.append(slug)
        return loaded

    def collect_ir_requirements(self, ir: dict[str, Any]) -> None:
        """Collect display series required to explain a strategy graph."""
        nodes = ir.get("nodes")
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_type = str(node.get("type") or "")
            params = node.get("params") if isinstance(node.get("params"), dict) else {}
            if node_type == "indicator":
                self._add_indicator(str(params.get("indicator") or ""), params)
            elif node_type in {"fresh_signal_state", "swing_low_state"}:
                for length in (
                    (20,) if node_type == "fresh_signal_state" else (20, 50, 100, 200)
                ):
                    self._add_indicator("ema", {"length": length})

    async def build(
        self,
        indicators: Indicators,
        candles: list[ChartCandle],
        replay_start_index: int,
    ) -> list[dict[str, Any]]:
        """Build chart series from causal indicator series."""
        result: list[dict[str, Any]] = []
        for requirement in self._requirements.values():
            series = await self._load_series(indicators, requirement)
            points = self._points(series, candles, replay_start_index)
            if not points:
                continue
            indicator = str(requirement["indicator"])
            pane, renderer, color = CHART_INDICATOR_STYLES[indicator]
            result.append(
                {
                    "key": self._key(requirement),
                    "label": self._label(requirement),
                    "pane": pane,
                    "renderer": renderer,
                    "color": color,
                    "values": points,
                }
            )
        return result

    def required_warmup_candles(self) -> int:
        """Return source candles needed before the visible chart window."""
        warmup = 0
        for requirement in self._requirements.values():
            indicator = str(requirement["indicator"])
            if indicator == "ema":
                length = int(requirement["length"])
                warmup = max(warmup, max(length * 2, 200))
            elif indicator == "rsi":
                length = int(requirement["length"])
                warmup = max(warmup, max(length * 3, 50))
            elif indicator.startswith("bollinger_"):
                length = int(requirement["length"])
                warmup = max(warmup, max(length * 3, 50))
            elif indicator.startswith("macd_"):
                slow_period = int(requirement["slow_period"])
                warmup = max(warmup, max(slow_period * 3, 100))
        return warmup

    def _add_indicator(self, indicator: str, params: dict[str, Any]) -> None:
        """Add normalized indicator requirements, including useful band context."""
        if indicator.startswith("bollinger_"):
            for component in ("upper", "middle", "lower"):
                self._store_indicator(f"bollinger_{component}", params)
            if indicator == "bollinger_bandwidth":
                self._store_indicator(indicator, params)
            return
        if indicator.startswith("macd_"):
            for component in ("line", "signal", "histogram"):
                self._store_indicator(f"macd_{component}", params)
            return
        self._store_indicator(indicator, params)

    def _store_indicator(self, indicator: str, params: dict[str, Any]) -> None:
        """Store one unique display indicator requirement."""
        if indicator not in CHART_INDICATOR_STYLES:
            return
        requirement = {"indicator": indicator}
        if indicator == "ema":
            requirement["length"] = int(params.get("length") or 20)
        elif indicator == "rsi":
            requirement["length"] = int(params.get("length") or 14)
        elif indicator.startswith("bollinger_"):
            requirement["length"] = int(params.get("length") or 20)
            requirement["standard_deviations"] = float(
                params.get("standard_deviations") or 2.0
            )
        elif indicator.startswith("macd_"):
            requirement["fast_period"] = int(params.get("fast_period") or 12)
            requirement["slow_period"] = int(params.get("slow_period") or 26)
            requirement["signal_period"] = int(params.get("signal_period") or 9)
        key = ":".join(str(requirement[field]) for field in requirement)
        self._requirements.setdefault(key, requirement)

    async def _load_series(
        self, indicators: Indicators, requirement: dict[str, Any]
    ) -> Any:
        """Load one indicator component for chart output."""
        indicator = str(requirement["indicator"])
        if indicator == "ema":
            return await indicators.calculate_ema_series(
                self.symbol, self.timeframe, int(requirement["length"])
            )
        if indicator == "rsi":
            return await indicators.calculate_rsi_series(
                self.symbol, self.timeframe, int(requirement["length"])
            )
        if indicator.startswith("bollinger_"):
            series = await indicators.calculate_bollinger_bands_series(
                self.symbol,
                self.timeframe,
                int(requirement["length"]),
                float(requirement["standard_deviations"]),
            )
            component = indicator.removeprefix("bollinger_")
            return series.get(component) if isinstance(series, dict) else None
        if indicator.startswith("macd_"):
            series = await indicators.calculate_macd_series(
                self.symbol,
                self.timeframe,
                int(requirement["fast_period"]),
                int(requirement["slow_period"]),
                int(requirement["signal_period"]),
            )
            component = indicator.removeprefix("macd_")
            key = "macd" if component == "line" else component
            return series.get(key) if isinstance(series, dict) else None
        return None

    @staticmethod
    def _points(
        series: Any, candles: list[ChartCandle], replay_start_index: int
    ) -> list[dict[str, float | int]]:
        """Return finite display points within the visible replay range."""
        points: list[dict[str, float | int]] = []
        for index in range(replay_start_index, len(candles)):
            try:
                value = float(series.iloc[index])
            except (AttributeError, IndexError, TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            points.append({"time": candles[index].timestamp, "value": value})
        return points

    @staticmethod
    def _key(requirement: dict[str, Any]) -> str:
        """Return a stable UI key for one indicator series."""
        return ":".join(str(value) for value in requirement.values())

    @staticmethod
    def _label(requirement: dict[str, Any]) -> str:
        """Return a compact legend label for one indicator series."""
        indicator = str(requirement["indicator"])
        if indicator == "ema":
            return f"EMA {requirement['length']}"
        if indicator == "rsi":
            return f"RSI {requirement['length']}"
        if indicator.startswith("bollinger_"):
            component = indicator.removeprefix("bollinger_").capitalize()
            return f"BB {component} {requirement['length']}"
        component = indicator.removeprefix("macd_").capitalize()
        return f"MACD {component}"
