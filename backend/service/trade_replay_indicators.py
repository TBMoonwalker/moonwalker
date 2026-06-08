"""Strategy indicator overlays for open and closed trade replay charts."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import helper
import pandas as pd
from service.config import Config
from service.data_ohlcv import resample_ohlcv_data, rows_to_dataframe
from service.data_timeframes import timeframe_to_milliseconds
from service.indicators import Indicators
from service.sqlite_timestamps import build_normalized_text_timestamp_sql
from service.strategy_chart_indicators import StrategyChartIndicatorBuilder
from service.trades import Trades
from tortoise import Tortoise
from tortoise.exceptions import BaseORMException

logging = helper.LoggerFactory.get_logger(
    "logs/trades.log",
    "trade_replay_indicators",
)

NORMALIZED_TIMESTAMP_SQL = build_normalized_text_timestamp_sql()


@dataclass(frozen=True)
class ReplayIndicatorCandle:
    """Single candle used to align replay indicator points."""

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class ReplayIndicatorData:
    """In-memory indicator data source for one replay chart window."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    async def get_data_for_pair(
        self, pair: str, timerange: str, length: int
    ) -> pd.DataFrame | None:
        """Return the replay chart candle frame."""
        return self._df

    async def get_data_for_pair_by_days(
        self, pair: str, lookback_days: int
    ) -> pd.DataFrame | None:
        """Return the replay chart candle frame."""
        return self._df

    async def get_latest_timestamp_for_pair(self, pair: str) -> float | None:
        """Return the latest timestamp in the replay candle frame."""
        if self._df.empty:
            return None
        return float(self._df["timestamp"].max())

    def resample_data(self, ohlcv: pd.DataFrame, timerange: str) -> pd.DataFrame | None:
        """Resample OHLCV data to the requested timerange."""
        return resample_ohlcv_data(ohlcv, timerange)


class TradeReplayIndicatorService:
    """Build strategy indicator payloads for trade replay charts."""

    def __init__(
        self,
        trades: Trades | None = None,
        config_snapshot_provider: Callable[[], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self.trades = trades or Trades()
        self._config_snapshot_provider = (
            config_snapshot_provider or self._load_config_snapshot
        )

    async def get_indicators(
        self,
        deal_id: str,
        timerange: str,
        timestamp_start: str | int | float,
        timestamp_end: str | int | float,
    ) -> dict[str, Any]:
        """Return strategy indicator overlays for a replay deal."""
        try:
            normalized_deal_id = str(UUID(str(deal_id)))
            start_ms = int(float(timestamp_start))
            end_ms = int(float(timestamp_end))
        except (TypeError, ValueError):
            return self._empty(timerange)

        if end_ms <= start_ms:
            return self._empty(timerange)

        executions = await self.trades.get_trade_executions(normalized_deal_id)
        strategies = self._execution_strategies(executions)
        source = "execution_ledger"
        if not strategies:
            strategies = await self._legacy_backfill_strategies(executions)
            if strategies:
                source = "legacy_config_backfill"
        symbol = self._execution_symbol(executions)
        if not symbol or not strategies:
            return self._empty(timerange)

        builder = StrategyChartIndicatorBuilder(symbol, str(timerange))
        loaded_strategies = await builder.collect_strategy_requirements(*strategies)
        if not loaded_strategies:
            return self._payload([], strategies, timerange, source)

        warmup_candles = builder.required_warmup_candles()
        timeframe_ms = timeframe_to_milliseconds(str(timerange))
        warmup_start_ms = max(0, start_ms - warmup_candles * timeframe_ms)
        candles = await self._load_candles(
            normalized_deal_id,
            symbol,
            str(timerange),
            warmup_start_ms,
            end_ms,
            visible_start_ms=start_ms,
        )
        if not candles:
            return self._payload([], strategies, timerange, source)

        data = ReplayIndicatorData(self._candles_to_dataframe(candles))
        indicators = Indicators(data=data)
        replay_start_index = self._first_visible_candle_index(candles, start_ms)
        return self._payload(
            await builder.build(indicators, candles, replay_start_index),
            loaded_strategies,
            timerange,
            source,
        )

    @staticmethod
    async def _load_config_snapshot() -> dict[str, Any]:
        """Return the current runtime config snapshot for legacy backfills."""
        return (await Config.instance()).snapshot()

    @staticmethod
    def _execution_strategies(executions: list[dict[str, Any]]) -> list[str]:
        """Return unique non-empty strategies in ledger order."""
        strategies: list[str] = []
        seen: set[str] = set()
        for execution in executions:
            strategy = str(execution.get("strategy_name") or "").strip()
            if not strategy or strategy in seen:
                continue
            seen.add(strategy)
            strategies.append(strategy)
        return strategies

    @staticmethod
    def _execution_symbol(executions: list[dict[str, Any]]) -> str | None:
        """Return the first non-empty execution symbol."""
        for execution in executions:
            symbol = str(execution.get("symbol") or "").strip()
            if symbol:
                return symbol
        return None

    async def _legacy_backfill_strategies(
        self, executions: list[dict[str, Any]]
    ) -> list[str]:
        """Derive visible legacy strategies when old executions lack metadata."""
        if not executions:
            return []
        try:
            config = await self._config_snapshot_provider()
        except (RuntimeError, TypeError, ValueError, BaseORMException) as exc:
            logging.warning(
                "Failed loading config for legacy replay indicator backfill: %s",
                exc,
            )
            return []

        strategy_candidates: list[Any] = []
        has_campaign_execution = any(
            str(execution.get("campaign_id") or "").strip()
            or str(execution.get("role") or "").strip() in {"partial_sell"}
            for execution in executions
        )
        if has_campaign_execution:
            strategy_candidates.extend(
                [
                    config.get("sidestep_bearish_strategy"),
                    config.get("sidestep_reentry_strategy"),
                ]
            )

        strategy_candidates.extend(
            [
                config.get("signal_strategy"),
                config.get("dca_strategy"),
            ]
        )
        return self._unique_strategy_names(strategy_candidates)

    @staticmethod
    def _unique_strategy_names(values: list[Any]) -> list[str]:
        """Return unique non-empty strategy names in input order."""
        strategies: list[str] = []
        seen: set[str] = set()
        for value in values:
            strategy = str(value or "").strip()
            if not strategy or strategy in seen:
                continue
            seen.add(strategy)
            strategies.append(strategy)
        return strategies

    async def _load_candles(
        self,
        deal_id: str,
        symbol: str,
        timerange: str,
        start_ms: int,
        end_ms: int,
        visible_start_ms: int | None = None,
    ) -> list[ReplayIndicatorCandle]:
        """Load archived candles first, then fall back to ticker history."""
        archived = await self._query_rows(
            table_name="tradereplaycandles",
            identity_column="deal_id",
            identity_value=deal_id,
            start_ms=start_ms,
            end_ms=end_ms,
            start_operator=">=",
        )
        if archived:
            warmup_end_ms = (
                visible_start_ms if visible_start_ms is not None else start_ms
            )
            ticker_warmup = await self._query_rows(
                table_name="tickers",
                identity_column="symbol",
                identity_value=symbol,
                start_ms=start_ms - 60_000,
                end_ms=warmup_end_ms,
                start_operator=">",
            )
            return await asyncio.to_thread(
                self._rows_to_candles,
                [*ticker_warmup, *archived],
                timerange,
            )

        ticker_rows = await self._query_rows(
            table_name="tickers",
            identity_column="symbol",
            identity_value=symbol,
            start_ms=start_ms - 60_000,
            end_ms=end_ms,
            start_operator=">",
        )
        return await asyncio.to_thread(self._rows_to_candles, ticker_rows, timerange)

    @staticmethod
    def _first_visible_candle_index(
        candles: list[ReplayIndicatorCandle],
        visible_start_ms: int,
    ) -> int:
        """Return the candle index where visible replay output begins."""
        for index, candle in enumerate(candles):
            if candle.timestamp >= visible_start_ms:
                return index
        return len(candles)

    async def _query_rows(
        self,
        *,
        table_name: str,
        identity_column: str,
        identity_value: str,
        start_ms: int,
        end_ms: int,
        start_operator: str,
    ) -> list[dict[str, Any]]:
        """Return raw OHLCV rows from an approved time-series table."""
        if table_name not in {"tickers", "tradereplaycandles"}:
            return []
        if identity_column not in {"symbol", "deal_id"}:
            return []
        try:
            return await Tortoise.get_connection("default").execute_query_dict(
                "SELECT timestamp, open, high, low, close, volume "
                f"FROM {table_name} "
                f"WHERE {identity_column} = ? "
                f"AND {NORMALIZED_TIMESTAMP_SQL} {start_operator} ? "
                f"AND {NORMALIZED_TIMESTAMP_SQL} <= ? "
                f"ORDER BY {NORMALIZED_TIMESTAMP_SQL}, timestamp",
                [identity_value, start_ms, end_ms],
            )
        except BaseORMException as exc:
            logging.warning(
                "Failed loading replay indicator candles for %s=%s: %s",
                identity_column,
                identity_value,
                exc,
            )
            return []

    @staticmethod
    def _rows_to_candles(
        rows: list[dict[str, Any]],
        timerange: str,
    ) -> list[ReplayIndicatorCandle]:
        """Convert raw DB rows into resampled replay candles."""
        if not rows:
            return []
        df = rows_to_dataframe(rows)
        resampled = resample_ohlcv_data(df, timerange)
        if resampled is None or resampled.empty:
            return []
        return [
            ReplayIndicatorCandle(
                timestamp=int(pd.Timestamp(row["timestamp"]).timestamp() * 1000),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in resampled.to_dict(orient="records")
        ]

    @staticmethod
    def _candles_to_dataframe(candles: list[ReplayIndicatorCandle]) -> pd.DataFrame:
        """Convert replay candles to the DataFrame shape expected by indicators."""
        return pd.DataFrame(
            [
                {
                    "timestamp": candle.timestamp,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
                for candle in candles
            ]
        )

    @staticmethod
    def _payload(
        indicators: list[dict[str, Any]],
        strategies: list[str],
        timerange: str,
        source: str = "execution_ledger",
    ) -> dict[str, Any]:
        """Return the public replay indicator response payload."""
        return {
            "indicators": indicators,
            "strategies": strategies,
            "timeframe": str(timerange),
            "source": source,
        }

    def _empty(self, timerange: str) -> dict[str, Any]:
        """Return an empty replay indicator payload."""
        return self._payload([], [], timerange)
