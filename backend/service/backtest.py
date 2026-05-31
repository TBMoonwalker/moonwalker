"""Backtest engine — candle-by-candle replay with DCA simulation.

Fetches historical OHLCV from the exchange, replays a strategy graph
candle-by-candle, simulates DCA lifecycle (entry, safety orders, TP/SL exits),
and returns synthetic trade results with chart markers and analytics stats.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timezone
from typing import Any

import helper
import pandas as pd
from service.analytics import compute_stats_from_trades
from service.data_ohlcv import resample_ohlcv_data
from service.dca_math import (
    BacktestTradeState,
    calculate_actual_pnl_percent,
    calculate_average_entry_price,
    calculate_stop_loss_price,
    calculate_take_profit_price,
    calculate_trade_profit_pct,
    check_stop_loss_hit,
    check_take_profit_hit,
    should_place_safety_order,
)
from service.exchange import Exchange
from service.indicators import Indicators
from service.strategy_capability import get_strategy_min_history_candles
from service.strategy_runtime import evaluate_strategy_graph

logging = helper.LoggerFactory.get_logger("logs/backtest.log", "backtest")

MAX_CANDLES = 20_000
OHLCV_PAGE_SIZE = 1000
OHLCV_PAGE_DELAY = 0.5

TRADE_MODE_DYNAMIC_DCA = "dynamic_dca"
TRADE_MODE_SIDESTEP = "sidestep"
SUPPORTED_TRADE_MODES = frozenset({TRADE_MODE_DYNAMIC_DCA, TRADE_MODE_SIDESTEP})

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


TIMEFRAME_TO_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


class BacktestValidationError(ValueError):
    """Raised when a backtest request is invalid before execution."""


class OhlcvCandle:
    """Single OHLCV candle with timestamp."""

    __slots__ = ("timestamp", "open", "high", "low", "close", "volume")

    def __init__(
        self,
        timestamp: int,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        self.timestamp = timestamp
        self.open = open_price
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


class BacktestTrade:
    """Closed trade record from backtest replay."""

    __slots__ = (
        "id",
        "symbol",
        "side",
        "deal_id",
        "open_timestamp",
        "open_price",
        "close_timestamp",
        "close_price",
        "amount",
        "cost",
        "fee",
        "profit",
        "profit_percent",
        "safety_orders_count",
        "duration",
        "sell_reason",
    )

    def __init__(
        self,
        trade: BacktestTradeState,
        exit_price: float,
        exit_timestamp: int,
    ) -> None:
        self.id = trade.entry_timestamp
        self.symbol = trade.symbol
        self.side = "long"
        self.deal_id = str(trade.entry_timestamp)
        self.open_timestamp = trade.entry_timestamp
        self.open_price = trade.entry_price
        self.close_timestamp = exit_timestamp
        self.close_price = exit_price
        self.amount = trade.total_amount
        self.cost = trade.total_cost
        self.fee = trade.fee
        self.profit = round(
            trade.total_amount
            * (
                exit_price
                - calculate_average_entry_price(
                    trade.total_cost, trade.fee, trade.total_amount
                )
            ),
            8,
        )
        self.profit_percent = round(
            calculate_trade_profit_pct(
                calculate_average_entry_price(
                    trade.total_cost, trade.fee, trade.total_amount
                ),
                exit_price,
                trade.fee,
            ),
            4,
        )
        self.safety_orders_count = trade.safety_orders_count
        open_dt = datetime.fromtimestamp(trade.entry_timestamp / 1000, tz=timezone.utc)
        close_dt = datetime.fromtimestamp(exit_timestamp / 1000, tz=timezone.utc)
        delta = close_dt - open_dt
        self.duration = str(int(delta.total_seconds()))
        self.sell_reason = trade.sell_reason

    def to_dict(self) -> dict[str, Any]:
        """Return trade as dict for chart markers and analytics."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "deal_id": self.deal_id,
            "open_timestamp": self.open_timestamp,
            "open_price": self.open_price,
            "close_timestamp": self.close_timestamp,
            "close_price": self.close_price,
            "amount": round(self.amount, 8),
            "cost": round(self.cost, 2),
            "fee": self.fee,
            "profit": round(self.profit, 2),
            "profit_percent": round(self.profit_percent, 2),
            "safety_orders_count": self.safety_orders_count,
            "duration": self.duration,
            "sell_reason": self.sell_reason,
            "open_date": datetime.fromtimestamp(
                self.open_timestamp / 1000, tz=timezone.utc
            ).isoformat(),
            "close_date": datetime.fromtimestamp(
                self.close_timestamp / 1000, tz=timezone.utc
            ).isoformat(),
        }


# ── OHLCV fetching ─────────────────────────────────────────────────────────────


async def fetch_ohlcv(
    config: dict[str, Any],
    symbol: str,
    timeframe: str,
    start_date: int = 0,
    end_date: int | None = None,
    max_candles: int = MAX_CANDLES,
) -> list[OhlcvCandle]:
    """Fetch historical OHLCV from exchange with pagination and rate-limit awareness.

    Args:
        config: Exchange config (exchange name, API keys, etc.)
        symbol: Trading pair (e.g. "BTC/USDT")
        timeframe: Candle timeframe (e.g. "1h", "5m")
        start_date: Unix ms to fetch from
        end_date: Unix ms to fetch until (exclusive, None = now)

    Returns:
        Sorted list of candles, oldest first.
    """
    exchange = Exchange()
    try:
        raw = await exchange.get_history_for_symbol_batched(
            config,
            symbol,
            timeframe,
            since=start_date if start_date > 0 else 0,
            until=end_date,
            page_size=OHLCV_PAGE_SIZE,
            max_candles=max_candles,
            page_delay=OHLCV_PAGE_DELAY,
        )

        return [
            OhlcvCandle(
                timestamp=int(c[0]),
                open_price=float(c[1]),
                high=float(c[2]),
                low=float(c[3]),
                close=float(c[4]),
                volume=float(c[5]),
            )
            for c in raw
        ]
    finally:
        await exchange.close()


# ── Indicator pre-computation ──────────────────────────────────────────────────


class BacktestData:
    """In-memory data source for backtest, replacing the DB-backed Data class."""

    def __init__(self, df: pd.DataFrame, timeframe: str) -> None:
        """Initialize with pre-resampled OHLCV DataFrame."""
        self._df = df
        self._timeframe = timeframe

    async def get_data_for_pair(
        self, pair: str, timerange: str, length: int
    ) -> pd.DataFrame | None:
        """Return the backtest DataFrame for the current candle window."""
        return self._df

    async def get_data_for_pair_by_days(
        self, pair: str, lookback_days: int
    ) -> pd.DataFrame | None:
        """Return the backtest DataFrame for the current candle window."""
        return self._df

    async def get_latest_timestamp_for_pair(self, pair: str) -> float | None:
        """Return the latest timestamp in the backtest DataFrame."""
        if self._df.empty:
            return None
        return float(self._df["timestamp"].max())

    def resample_data(self, ohlcv: pd.DataFrame, timerange: str) -> pd.DataFrame | None:
        """Resample OHLCV data to the requested timerange."""
        return resample_ohlcv_data(ohlcv, timerange)


def candles_to_dataframe(candles: list[OhlcvCandle]) -> pd.DataFrame:
    """Convert OhlcvCandle list to OHLCV DataFrame."""
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(
        [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
    )
    return df


# ── DCA Simulation ─────────────────────────────────────────────────────────────


class DcaSimulator:
    """Simulate a DCA lifecycle for backtest replay.

    Manages entry, safety orders, TP and SL for a single trade.

    Intra-candle collision priority (documented per D7):
    TP > SL > SafetyOrder.  If a candle touches both TP high and
    SL low, taking profit always wins because a spike above TP is a
    genuine exit in real markets.
    """

    def __init__(
        self,
        base_order_size: float,
        take_profit_pct: float,
        stop_loss_pct: float | None,
        max_safety_orders: int,
        safety_order_step_pct: float = 3.0,
        fee: float = 0.001,
        allow_safety_orders: bool = True,
    ) -> None:
        self.base_order_size = base_order_size
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.max_safety_orders = max_safety_orders
        self.safety_order_step_pct = safety_order_step_pct
        self.fee = fee
        self.allow_safety_orders = allow_safety_orders

    def try_enter(
        self, symbol: str, entry_price: float, timestamp: int
    ) -> BacktestTradeState | None:
        """Open a new trade at the given entry price.

        Returns None if trade cannot be opened.
        """
        if entry_price <= 0:
            return None
        amount = self.base_order_size / entry_price
        return BacktestTradeState(
            symbol=symbol,
            entry_price=entry_price,
            entry_amount=amount,
            entry_cost=self.base_order_size,
            entry_timestamp=timestamp,
            fee=self.fee,
            total_amount=amount,
            total_cost=self.base_order_size,
        )

    def evaluate(
        self, trade: BacktestTradeState, candle: OhlcvCandle
    ) -> BacktestTrade | None:
        """Evaluate trade against a candle; may close or add safety orders.

        Intra-candle collision order: TP first, then SL, then safety orders.
        TP > SL > SO (see class docstring).

        Returns BacktestTrade if the trade closed, None otherwise.
        """
        if trade.closed:
            return None

        avg_price = calculate_average_entry_price(
            trade.total_cost, trade.fee, trade.total_amount
        )
        tp_price = calculate_take_profit_price(
            avg_price, self.take_profit_pct, trade.fee
        )

        # TP check first (highest priority in intra-candle collision)
        if check_take_profit_hit(
            trade.total_cost / trade.total_amount, tp_price, candle.high
        ):
            trade.closed = True
            trade.exit_price = tp_price
            trade.exit_timestamp = candle.timestamp
            trade.sell_reason = "take_profit"
            return BacktestTrade(trade, tp_price, candle.timestamp)

        # SL check second (only fires if all safety orders exhausted)
        if self.stop_loss_pct is not None:
            sl_price = calculate_stop_loss_price(
                avg_price, self.stop_loss_pct, trade.fee
            )
            if check_stop_loss_hit(
                trade.total_cost / trade.total_amount,
                sl_price,
                trade.safety_orders_count >= self.max_safety_orders,
                candle.low,
            ):
                trade.closed = True
                trade.exit_price = sl_price
                trade.exit_timestamp = candle.timestamp
                trade.sell_reason = "stop_loss"
                return BacktestTrade(trade, sl_price, candle.timestamp)

        # Safety order evaluation last
        actual_pnl = calculate_actual_pnl_percent(
            trade.total_cost,
            trade.fee,
            trade.total_amount,
            candle.close,
        )

        if self.allow_safety_orders and should_place_safety_order(
            actual_pnl=actual_pnl,
            trigger_threshold=self._next_safety_order_threshold(trade),
            max_safety_orders=self.max_safety_orders,
            current_safety_orders=trade.safety_orders_count,
        ):
            so_size = self.base_order_size * (1 + trade.safety_orders_count * 0.5)
            so_amount = so_size / candle.close
            trade.total_cost += so_size
            trade.total_amount += so_amount
            trade.safety_orders_count += 1
            trade.safety_orders.append(
                {
                    "index": trade.safety_orders_count,
                    "price": candle.close,
                    "amount": so_amount,
                    "cost": so_size,
                    "timestamp": candle.timestamp,
                    "so_percentage": round(actual_pnl, 1),
                }
            )

        return None

    def _next_safety_order_threshold(self, trade: BacktestTradeState) -> float:
        """Return the next dynamic DCA trigger threshold."""
        if not trade.safety_orders:
            return -abs(self.safety_order_step_pct)
        last_percentage = trade.safety_orders[-1].get("so_percentage")
        try:
            return float(last_percentage) - abs(self.safety_order_step_pct)
        except (TypeError, ValueError):
            return -abs(self.safety_order_step_pct * (trade.safety_orders_count + 1))


# ── Main Backtest engine ──────────────────────────────────────────────────────


class Backtest:
    """Candle-by-candle backtest engine.

    Fetches historical OHLCV, evaluates strategy graph per candle,
    simulates DCA lifecycle, and returns analytics-ready results.
    """

    def __init__(
        self,
        config: dict[str, Any],
        strategy_slug: str,
        timeframe: str,
        symbol: str,
        start_date: datetime | str,
        end_date: datetime | str,
        base_order_size: float = 20.0,
        take_profit_pct: float = 2.5,
        stop_loss_pct: float | None = None,
        max_safety_orders: int = 5,
        safety_order_step_pct: float = 3.0,
        fee: float = 0.001,
        trade_mode: str = TRADE_MODE_DYNAMIC_DCA,
        sidestep_bearish_strategy: str | None = None,
        sidestep_reentry_strategy: str | None = None,
    ) -> None:
        self.config = config
        self.strategy_slug = strategy_slug
        self.timeframe = timeframe
        self.symbol = symbol
        self.start_date = _datetime_to_ms(_coerce_datetime(start_date, "start_date"))
        self.end_date = _datetime_to_ms(_coerce_datetime(end_date, "end_date"))
        validate_backtest_range(self.timeframe, self.start_date, self.end_date)
        self._warmup_candle_count = self._resolve_warmup_candle_count(
            strategy_slug,
            sidestep_bearish_strategy,
            sidestep_reentry_strategy,
        )
        self._fetch_start_date = max(
            0,
            self.start_date
            - self._warmup_candle_count * TIMEFRAME_TO_MS.get(self.timeframe, 0),
        )
        self.base_order_size = _positive_float(base_order_size, "base_order_size")
        self.take_profit_pct = _non_negative_float(take_profit_pct, "take_profit_pct")
        self.stop_loss_pct = _optional_non_negative_float(
            stop_loss_pct, "stop_loss_pct"
        )
        self.max_safety_orders = _non_negative_int(
            max_safety_orders, "max_safety_orders"
        )
        self.safety_order_step_pct = _positive_float(
            safety_order_step_pct, "safety_order_step_pct"
        )
        self.fee = _non_negative_float(fee, "fee")
        self.trade_mode = _trade_mode(trade_mode)
        self.sidestep_bearish_strategy = _strategy_slug(
            sidestep_bearish_strategy,
            "sidestep_bearish_strategy",
            required=self.trade_mode == TRADE_MODE_SIDESTEP,
        )
        self.sidestep_reentry_strategy = _strategy_slug(
            sidestep_reentry_strategy,
            "sidestep_reentry_strategy",
            required=self.trade_mode == TRADE_MODE_SIDESTEP,
        )
        self._candles: list[OhlcvCandle] | None = None
        self._indicators: Indicators | None = None
        self._open_trade: BacktestTradeState | None = None
        self._closed_trades: list[BacktestTrade] = []
        self._chart_markers: list[dict[str, Any]] = []
        self._still_open_at_end: bool = False
        self._sidestep_waiting_at_end: bool = False
        self._state_store: dict[tuple[str, str, str, str], Any] = {}
        self._chart_indicator_requirements: dict[str, dict[str, Any]] = {}
        self._chart_indicators: list[dict[str, Any]] = []

    async def run(self) -> dict[str, Any]:
        """Execute backtest and return results.

        Returns:
            Dict with 'trades', 'chart', 'stats' keys.
        """
        candles = await self._fetch()
        replay_start_index = self._first_replay_index(candles)
        replay_candles = candles[replay_start_index:]
        if len(replay_candles) < 2:
            return self._empty_result(replay_candles, len(candles), replay_start_index)

        df = candles_to_dataframe(candles)
        backtest_data = BacktestData(df, self.timeframe)
        indicators = Indicators(data=backtest_data)

        simulator = DcaSimulator(
            base_order_size=self.base_order_size,
            take_profit_pct=self.take_profit_pct,
            stop_loss_pct=self.stop_loss_pct,
            max_safety_orders=(
                self.max_safety_orders
                if self.trade_mode == TRADE_MODE_DYNAMIC_DCA
                else 0
            ),
            safety_order_step_pct=self.safety_order_step_pct,
            fee=self.fee,
            allow_safety_orders=self.trade_mode == TRADE_MODE_DYNAMIC_DCA,
        )

        if self.trade_mode == TRADE_MODE_SIDESTEP:
            await self._run_sidestep(
                candles,
                indicators,
                simulator,
                replay_start_index,
            )
        else:
            await self._run_dynamic_dca(
                candles,
                indicators,
                simulator,
                replay_start_index,
            )

        self._chart_indicators = await self._build_chart_indicators(
            indicators,
            candles,
            replay_start_index,
        )
        return self._build_result(replay_candles, len(candles), replay_start_index)

    async def _run_dynamic_dca(
        self,
        candles: list[OhlcvCandle],
        indicators: Indicators,
        simulator: DcaSimulator,
        replay_start_index: int = 0,
    ) -> None:
        """Replay the default dynamic DCA lifecycle."""
        await self._preload_strategy_snapshots(self.strategy_slug)
        await self._warm_strategy_state(
            ((self.strategy_slug, "buy"),),
            indicators,
            replay_start_index,
        )

        for idx in range(replay_start_index, len(candles) - 1):
            candle = candles[idx]
            next_candle = candles[idx + 1]

            # 1. Evaluate existing trade against CURRENT candle (eval before signal)
            if self._open_trade:
                previous_safety_orders = self._open_trade.safety_orders_count
                closed = simulator.evaluate(self._open_trade, candle)
                if closed:
                    self._closed_trades.append(closed)
                    self._chart_markers.append(
                        {
                            "time": closed.close_timestamp,
                            "position": "aboveBar",
                            "color": "#B4443F",
                            "shape": "arrow_down",
                            "text": closed.sell_reason or "SELL",
                        }
                    )
                    self._open_trade = None
                elif self._open_trade.safety_orders_count > previous_safety_orders:
                    self._append_safety_order_marker(self._open_trade)

            # 2. Check for new entry signal on current candle
            if not self._open_trade:
                result = await self._evaluate_strategy(
                    self.strategy_slug,
                    "buy",
                    indicators,
                    idx,
                )

                if result.matched:
                    trade = simulator.try_enter(
                        self.symbol, next_candle.open, next_candle.timestamp
                    )
                    if trade:
                        self._open_trade = trade
                        self._append_buy_marker(next_candle.timestamp, "BO")

        if self._open_trade is not None:
            previous_safety_orders = self._open_trade.safety_orders_count
            closed = simulator.evaluate(self._open_trade, candles[-1])
            if closed:
                self._closed_trades.append(closed)
                self._chart_markers.append(
                    {
                        "time": closed.close_timestamp,
                        "position": "aboveBar",
                        "color": "#B4443F",
                        "shape": "arrow_down",
                        "text": closed.sell_reason or "SELL",
                    }
                )
                self._open_trade = None
            elif self._open_trade.safety_orders_count > previous_safety_orders:
                self._append_safety_order_marker(self._open_trade)

        # Log still-open trade at end of range
        if self._open_trade is not None:
            self._still_open_at_end = True
            logging.warning(
                "Backtest for %s ended with trade still open (entry: %s). "
                "Excluded from stats.",
                self.symbol,
                self._open_trade.entry_timestamp,
            )

    async def _run_sidestep(
        self,
        candles: list[OhlcvCandle],
        indicators: Indicators,
        simulator: DcaSimulator,
        replay_start_index: int = 0,
    ) -> None:
        """Replay spot sidestep: re-entry opens, bearish signal exits to flat."""
        bearish_strategy = self.sidestep_bearish_strategy or ""
        reentry_strategy = self.sidestep_reentry_strategy or ""
        await self._preload_strategy_snapshots(bearish_strategy, reentry_strategy)
        await self._warm_strategy_state(
            ((bearish_strategy, "sell"), (reentry_strategy, "buy")),
            indicators,
            replay_start_index,
        )

        for idx in range(replay_start_index, len(candles) - 1):
            candle = candles[idx]
            next_candle = candles[idx + 1]

            if self._open_trade:
                closed = simulator.evaluate(self._open_trade, candle)
                if closed:
                    self._append_closed_trade_marker(closed)
                    self._open_trade = None
                    self._sidestep_waiting_at_end = False
                    continue

                exit_signal = await self._evaluate_strategy(
                    bearish_strategy,
                    "sell",
                    indicators,
                    idx,
                )
                if exit_signal.matched:
                    trade = self._open_trade
                    trade.closed = True
                    trade.exit_price = next_candle.open
                    trade.exit_timestamp = next_candle.timestamp
                    trade.sell_reason = "sidestep_exit"
                    closed = BacktestTrade(
                        trade, next_candle.open, next_candle.timestamp
                    )
                    self._closed_trades.append(closed)
                    self._chart_markers.append(
                        {
                            "time": closed.close_timestamp,
                            "position": "aboveBar",
                            "color": "#B7791F",
                            "shape": "arrow_down",
                            "text": "SIDESTEP",
                        }
                    )
                    self._open_trade = None
                    self._sidestep_waiting_at_end = True
                    continue

            if not self._open_trade:
                entry_signal = await self._evaluate_strategy(
                    reentry_strategy,
                    "buy",
                    indicators,
                    idx,
                )
                if entry_signal.matched:
                    trade = simulator.try_enter(
                        self.symbol, next_candle.open, next_candle.timestamp
                    )
                    if trade:
                        self._open_trade = trade
                        self._sidestep_waiting_at_end = False
                        self._chart_markers.append(
                            {
                                "time": next_candle.timestamp,
                                "position": "belowBar",
                                "color": "#2E7D5B",
                                "shape": "arrow_up",
                                "text": "RE-ENTRY",
                            }
                        )

        if self._open_trade is not None:
            closed = simulator.evaluate(self._open_trade, candles[-1])
            if closed:
                self._append_closed_trade_marker(closed)
                self._open_trade = None
                self._sidestep_waiting_at_end = False

        if self._open_trade is not None:
            self._still_open_at_end = True
            logging.warning(
                "Sidestep backtest for %s ended with trade still open (entry: %s). "
                "Excluded from stats.",
                self.symbol,
                self._open_trade.entry_timestamp,
            )

    async def _preload_strategy_snapshots(self, *slugs: str) -> None:
        """Preload strategy snapshots once before candle replay."""
        from service.strategy_runtime import _load_strategy_snapshot as _lsnap

        for slug in dict.fromkeys(
            str(slug).strip() for slug in slugs if str(slug).strip()
        ):
            snapshot = await _lsnap(slug)
            ir = getattr(snapshot, "ir", None)
            if isinstance(ir, dict):
                self._collect_chart_indicator_requirements(ir)

    def _collect_chart_indicator_requirements(self, ir: dict[str, Any]) -> None:
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
                self._add_chart_indicator(str(params.get("indicator") or ""), params)
            elif node_type in {"fresh_signal_state", "swing_low_state"}:
                for length in (
                    (20,) if node_type == "fresh_signal_state" else (20, 50, 100, 200)
                ):
                    self._add_chart_indicator("ema", {"length": length})

    def _add_chart_indicator(self, indicator: str, params: dict[str, Any]) -> None:
        """Add normalized indicator requirements, including useful band context."""
        if indicator.startswith("bollinger_"):
            for component in ("upper", "middle", "lower"):
                self._store_chart_indicator(f"bollinger_{component}", params)
            if indicator == "bollinger_bandwidth":
                self._store_chart_indicator(indicator, params)
            return
        if indicator.startswith("macd_"):
            for component in ("line", "signal", "histogram"):
                self._store_chart_indicator(f"macd_{component}", params)
            return
        self._store_chart_indicator(indicator, params)

    def _store_chart_indicator(self, indicator: str, params: dict[str, Any]) -> None:
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
        self._chart_indicator_requirements.setdefault(key, requirement)

    async def _build_chart_indicators(
        self,
        indicators: Indicators,
        candles: list[OhlcvCandle],
        replay_start_index: int,
    ) -> list[dict[str, Any]]:
        """Build chart series from the same causal series used for evaluation."""
        result: list[dict[str, Any]] = []
        for requirement in self._chart_indicator_requirements.values():
            series = await self._load_chart_indicator_series(indicators, requirement)
            points = self._chart_indicator_points(series, candles, replay_start_index)
            if not points:
                continue
            indicator = str(requirement["indicator"])
            pane, renderer, color = CHART_INDICATOR_STYLES[indicator]
            result.append(
                {
                    "key": self._chart_indicator_key(requirement),
                    "label": self._chart_indicator_label(requirement),
                    "pane": pane,
                    "renderer": renderer,
                    "color": color,
                    "values": points,
                }
            )
        return result

    async def _load_chart_indicator_series(
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

    def _chart_indicator_points(
        self, series: Any, candles: list[OhlcvCandle], replay_start_index: int
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

    def _chart_indicator_key(self, requirement: dict[str, Any]) -> str:
        """Return a stable UI key for one indicator series."""
        return ":".join(str(value) for value in requirement.values())

    def _chart_indicator_label(self, requirement: dict[str, Any]) -> str:
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

    async def _evaluate_strategy(
        self,
        strategy_slug: str,
        side: str,
        indicators: Indicators,
        candle_index: int,
    ) -> Any:
        """Evaluate one strategy graph against the current replay candle."""
        return await evaluate_strategy_graph(
            strategy_slug,
            self.timeframe,
            self.symbol,
            side,
            indicators,
            candle_index=candle_index,
            state_store=self._state_store,
        )

    async def _warm_strategy_state(
        self,
        strategies: tuple[tuple[str, str], ...],
        indicators: Indicators,
        replay_start_index: int,
    ) -> None:
        """Advance stateful strategy memory before the visible replay window."""
        for idx in range(replay_start_index):
            for slug, side in strategies:
                await self._evaluate_strategy(slug, side, indicators, idx)

    def _append_buy_marker(self, timestamp: int, text: str) -> None:
        """Append a buy marker for a base or re-entry order."""
        self._chart_markers.append(
            {
                "time": timestamp,
                "position": "belowBar",
                "color": "#2E7D5B",
                "shape": "arrow_up",
                "text": text,
            }
        )

    def _append_safety_order_marker(self, trade: BacktestTradeState) -> None:
        """Append a marker for the latest safety order."""
        if not trade.safety_orders:
            return
        safety_order = trade.safety_orders[-1]
        self._chart_markers.append(
            {
                "time": int(safety_order["timestamp"]),
                "position": "belowBar",
                "color": "#356D86",
                "shape": "circle",
                "text": f"SO {int(safety_order['index'])}",
            }
        )

    def _append_closed_trade_marker(self, closed: BacktestTrade) -> None:
        """Append a standard sell marker for a closed replay trade."""
        self._closed_trades.append(closed)
        self._chart_markers.append(
            {
                "time": closed.close_timestamp,
                "position": "aboveBar",
                "color": "#B4443F",
                "shape": "arrow_down",
                "text": closed.sell_reason or "SELL",
            }
        )

    async def _fetch(self) -> list[OhlcvCandle]:
        """Fetch OHLCV for the configured range."""
        if self._candles is None:
            self._candles = await fetch_ohlcv(
                self.config,
                self.symbol,
                self.timeframe,
                self._fetch_start_date,
                self.end_date,
                max_candles=MAX_CANDLES + self._warmup_candle_count,
            )
        return self._candles

    def _empty_result(
        self,
        candles: list[OhlcvCandle],
        total_candles_fetched: int | None = None,
        warmup_candles: int = 0,
    ) -> dict[str, Any]:
        """Return empty result when no meaningful backtest can run."""
        ohlcv = self._candles_to_ohlcv_payload(candles)
        stats = compute_stats_from_trades([])
        stats.update(
            {
                "candles_fetched": total_candles_fetched or len(candles),
                "candles_evaluated": 0,
                "warmup_candles": warmup_candles,
                "timeframe": self.timeframe,
                "symbol": self.symbol,
                "strategy": self.strategy_slug,
                "trade_mode": self.trade_mode,
                "sidestep_bearish_strategy": self.sidestep_bearish_strategy,
                "sidestep_reentry_strategy": self.sidestep_reentry_strategy,
                "still_open_at_end": False,
                "sidestep_waiting_at_end": False,
            }
        )
        return {
            "trades": [],
            "chart": {"candles": ohlcv, "markers": [], "indicators": []},
            "stats": stats,
        }

    def _build_result(
        self,
        candles: list[OhlcvCandle],
        total_candles_fetched: int | None = None,
        warmup_candles: int = 0,
    ) -> dict[str, Any]:
        """Build final backtest result with trades, chart data, and stats."""
        closed_trades = [t.to_dict() for t in self._closed_trades]
        stats = compute_stats_from_trades(closed_trades)
        stats.update(
            {
                "candles_fetched": total_candles_fetched or len(candles),
                "candles_evaluated": min(len(candles) - 1, len(candles)),
                "warmup_candles": warmup_candles,
                "timeframe": self.timeframe,
                "symbol": self.symbol,
                "strategy": self.strategy_slug,
                "trade_mode": self.trade_mode,
                "sidestep_bearish_strategy": self.sidestep_bearish_strategy,
                "sidestep_reentry_strategy": self.sidestep_reentry_strategy,
                "still_open_at_end": self._still_open_at_end,
                "sidestep_waiting_at_end": self._sidestep_waiting_at_end,
            }
        )

        return {
            "trades": closed_trades,
            "chart": {
                "candles": self._candles_to_ohlcv_payload(candles),
                "markers": self._chart_markers,
                "indicators": self._chart_indicators,
            },
            "stats": stats,
        }

    def _candles_to_ohlcv_payload(
        self, candles: list[OhlcvCandle]
    ) -> list[dict[str, Any]]:
        """Convert candles to chart-compatible payload."""
        return [
            {
                "time": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]

    def _first_replay_index(self, candles: list[OhlcvCandle]) -> int:
        """Return the first candle index inside the requested replay window."""
        for index, candle in enumerate(candles):
            if candle.timestamp >= self.start_date:
                return index
        return 0

    def _resolve_warmup_candle_count(self, *strategies: str | None) -> int:
        """Return the max warmup candles required by configured strategies."""
        return max(
            (
                get_strategy_min_history_candles(strategy)
                for strategy in strategies
                if strategy
            ),
            default=0,
        )


# ── Helpers ────────────────────────────────────────────────────────────────────


def _coerce_datetime(value: datetime | str, field: str) -> datetime:
    """Normalize accepted date inputs to timezone-aware UTC datetimes."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        raw = float(value)
        timestamp = raw / 1000 if raw > 10_000_000_000 else raw
        parsed = datetime.fromtimestamp(timestamp, tz=UTC)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise BacktestValidationError(f"{field} is required")
        if stripped.isdigit():
            parsed = _coerce_datetime(int(stripped), field)
        else:
            try:
                parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            except ValueError as exc:
                raise BacktestValidationError(f"Invalid {field}: {value}") from exc
    else:
        raise BacktestValidationError(f"Invalid {field}: {value}")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _datetime_to_ms(value: datetime) -> int:
    """Return an aware datetime as Unix milliseconds."""
    return int(value.timestamp() * 1000)


def estimate_candle_count(timeframe: str, start_ms: int, end_ms: int) -> int:
    """Estimate candle count for a timeframe and date range."""
    timeframe_ms = TIMEFRAME_TO_MS.get(str(timeframe))
    if timeframe_ms is None:
        raise BacktestValidationError(f"Unsupported timeframe: {timeframe}")
    return max(0, int((end_ms - start_ms) / timeframe_ms) + 1)


def validate_backtest_range(timeframe: str, start_ms: int, end_ms: int) -> None:
    """Validate range ordering and estimated candle count."""
    if end_ms <= start_ms:
        raise BacktestValidationError("end_date must be after start_date")

    estimated = estimate_candle_count(timeframe, start_ms, end_ms)
    if estimated > MAX_CANDLES:
        raise BacktestValidationError(
            f"Backtest range too large for {timeframe}: estimated {estimated} "
            f"candles (max {MAX_CANDLES})"
        )


def _positive_float(value: Any, field: str) -> float:
    """Return a positive float or raise a validation error."""
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise BacktestValidationError(f"{field} must be a number") from exc
    if parsed <= 0:
        raise BacktestValidationError(f"{field} must be greater than 0")
    return parsed


def _non_negative_float(value: Any, field: str) -> float:
    """Return a non-negative float or raise a validation error."""
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise BacktestValidationError(f"{field} must be a number") from exc
    if parsed < 0:
        raise BacktestValidationError(f"{field} must be greater than or equal to 0")
    return parsed


def _optional_non_negative_float(value: Any, field: str) -> float | None:
    """Return an optional non-negative float or None when omitted."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _non_negative_float(value, field)


def _non_negative_int(value: Any, field: str) -> int:
    """Return a non-negative integer or raise a validation error."""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise BacktestValidationError(f"{field} must be an integer") from exc
    if parsed < 0:
        raise BacktestValidationError(f"{field} must be greater than or equal to 0")
    return parsed


def _trade_mode(value: Any) -> str:
    """Return a supported trade mode or raise a validation error."""
    normalized = str(value or TRADE_MODE_DYNAMIC_DCA).strip().lower()
    if normalized not in SUPPORTED_TRADE_MODES:
        raise BacktestValidationError(f"Unsupported trade_mode: {value}")
    return normalized


def _strategy_slug(value: Any, field: str, *, required: bool) -> str | None:
    """Normalize optional strategy slugs used by sidestep replay."""
    normalized = str(value or "").strip()
    if required and not normalized:
        raise BacktestValidationError(f"{field} is required for sidestep backtests")
    return normalized or None
