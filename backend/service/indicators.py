"""Indicator calculations based on OHLCV data."""

import asyncio
from collections import deque
from typing import Any

import helper
import pandas as pd
import talib
from service.data import Data

logging = helper.LoggerFactory.get_logger("logs/indicators.log", "indicators")


class Indicators:
    """Compute technical indicators used by strategies."""

    EMA_SEED_BUFFER = 20

    def __init__(self) -> None:
        self.data = Data()
        self._state_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._state: dict[tuple[str, str], dict[str, Any]] = {}

    def _get_lock(self, key: tuple[str, str]) -> asyncio.Lock:
        lock = self._state_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._state_locks[key] = lock
        return lock

    @staticmethod
    def _timeframe_to_seconds(timerange: str) -> int | None:
        value = timerange.strip().lower()
        if not value:
            return None
        try:
            if value.endswith("min"):
                return int(value[:-3]) * 60
            if value.endswith("m"):
                return int(value[:-1]) * 60
            if value.endswith("h"):
                return int(value[:-1]) * 3600
            if value.endswith("d"):
                return int(value[:-1]) * 86400
            if value.endswith("w"):
                return int(value[:-1]) * 604800
        except ValueError:
            return None
        return None

    async def _seed_state(
        self,
        symbol: str,
        timerange: str,
        lengths: set[int],
        close_window: int,
        latest_candle: tuple[float, float],
    ) -> dict[str, Any] | None:
        max_length = max(lengths) if lengths else 1
        fetch_length = max(max_length + self.EMA_SEED_BUFFER, close_window + 5)
        df_raw = await self.data.get_data_for_pair(symbol, timerange, fetch_length)
        df = self.data.resample_data(df_raw, timerange)
        if df is None or df.empty:
            return None

        close_series = df["close"].dropna()
        if close_series.empty:
            return None

        closes = [float(value) for value in close_series.tolist()]
        ema_values: dict[int, float] = {}
        for length in lengths:
            if len(closes) < length:
                raise ValueError(
                    f"Not enough candles to seed EMA{length} for {symbol}/{timerange}"
                )
            ema_series = talib.EMA(close_series, timeperiod=length).dropna()
            if ema_series.empty:
                raise ValueError(
                    f"TA-Lib returned empty EMA{length} for {symbol}/{timerange}"
                )
            ema_values[length] = float(ema_series.iloc[-1])

        window_size = max(close_window, 5)
        close_values: deque[float] = deque(closes[-window_size:], maxlen=window_size)
        return {
            "last_timestamp": float(latest_candle[0]),
            "last_close": float(latest_candle[1]),
            "ema_values": ema_values,
            "close_values": close_values,
            "max_close_window": window_size,
        }

    async def _ensure_state(
        self,
        symbol: str,
        timerange: str,
        lengths: set[int] | None = None,
        close_window: int = 5,
    ) -> dict[str, Any] | None:
        state_key = (symbol, timerange)
        lock = self._get_lock(state_key)
        requested_lengths = lengths or set()

        async with lock:
            latest_candle = await self.data.get_latest_candle_for_pair(symbol)
            if latest_candle is None:
                return None

            state = self._state.get(state_key)
            needs_reseed = state is None
            if not needs_reseed:
                if not requested_lengths.issubset(state["ema_values"].keys()):
                    needs_reseed = True
                elif close_window > state["max_close_window"]:
                    needs_reseed = True

            if needs_reseed:
                state = await self._seed_state(
                    symbol=symbol,
                    timerange=timerange,
                    lengths=requested_lengths,
                    close_window=close_window,
                    latest_candle=latest_candle,
                )
                if state is None:
                    return None
                self._state[state_key] = state
                return state

            latest_timestamp, latest_close = latest_candle
            last_timestamp = float(state["last_timestamp"])
            if latest_timestamp <= last_timestamp:
                return state

            # If data jumped more than one candle, reseed for exact indicator values.
            timeframe_seconds = self._timeframe_to_seconds(timerange)
            if timeframe_seconds:
                expected_step_ms = timeframe_seconds * 1000
                if latest_timestamp - last_timestamp > (expected_step_ms * 1.5):
                    reseeded = await self._seed_state(
                        symbol=symbol,
                        timerange=timerange,
                        lengths=set(state["ema_values"].keys()),
                        close_window=state["max_close_window"],
                        latest_candle=latest_candle,
                    )
                    if reseeded is not None:
                        self._state[state_key] = reseeded
                        return reseeded

            # Incremental one-candle EMA update.
            for length, prev_ema in state["ema_values"].items():
                alpha = 2.0 / (float(length) + 1.0)
                state["ema_values"][length] = float(
                    prev_ema + alpha * (latest_close - prev_ema)
                )

            close_values: deque[float] = state["close_values"]
            close_values.append(float(latest_close))
            state["last_timestamp"] = float(latest_timestamp)
            state["last_close"] = float(latest_close)
            return state

    # async def calculate_bbands_cross(self, symbol, timerange, length):
    #     result = "none"
    #     try:
    #         df_raw = await self.data.get_data_for_pair(symbol, timerange, length)
    #         df = self.data.resample_data(df_raw, timerange)
    #         df["upper_band"], df["middle_band"], df["lower_band"] = talib.BBANDS(
    #             df["close"], timeperiod=length
    #         )
    #         df.dropna(subset=["upper_band", "middle_band", "lower_band"], inplace=True)
    #         percent_difference_downtrend = 0
    #         percent_difference_uptrend = 0
    #         if df["close"].iloc[-2] < df["lower_band"].iloc[-2]:
    #             percent_difference_downtrend = (
    #                 abs(df["lower_band"].iloc[-2] - df["close"].iloc[-2])
    #                 / ((df["lower_band"].iloc[-2] + df["close"].iloc[-2]) / 2)
    #                 * 10
    #             )
    #         if df["close"].iloc[-1] > df["lower_band"].iloc[-1]:
    #             percent_difference_uptrend = (
    #                 abs(df["lower_band"].iloc[-1] - df["close"].iloc[-1])
    #                 / ((df["lower_band"].iloc[-1] + df["close"].iloc[-1]) / 2)
    #                 * 100
    #             )

    #         logging.debug(
    #             f"Symbol: {symbol}, Price: {df['close'].iloc[-1]}, LowerBand: {df['lower_band'].iloc[-1]}"
    #         )
    #         logging.debug(
    #             f"Symbol: {symbol}, downtrend: {percent_difference_downtrend}, uptrend: {percent_difference_uptrend}"
    #         )

    #         if percent_difference_downtrend > 0.1 and (
    #             percent_difference_uptrend > 0.1 and percent_difference_uptrend < 0.5
    #         ):
    #             result = True
    #     except Exception as e:
    #         logging.error(f"BBANDS cross cannot be calculated for {symbol}. Cause: {e}")

    #     return result

    async def calculate_ema(
        self, symbol: str, timerange: str, lengths: list[int]
    ) -> dict[str, Any]:
        """Calculate EMA values for the given lengths."""
        try:
            state = await self._ensure_state(
                symbol=symbol,
                timerange=timerange,
                lengths=set(lengths),
                close_window=5,
            )
            if state is None:
                return {}

            result: dict[str, Any] = {}
            for length in lengths:
                result[f"ema_{length}"] = state["ema_values"].get(length)
            return result
        except Exception as e:
            logging.error(f"EMA cannot be calculated for {symbol}. Cause: {e}")
            return {}

    async def get_close_price(self, symbol: str, timerange: str, length: int) -> Any:
        """Return close price series for a symbol."""
        try:
            state = await self._ensure_state(
                symbol=symbol,
                timerange=timerange,
                lengths=set(),
                close_window=max(length, 5),
            )
            if state is None:
                return None
            values = list(state["close_values"])[-max(length, 1) :]
            return pd.Series(values)
        except Exception as e:
            # Broad catch to avoid breaking strategy execution.
            logging.error(f"Close price cannot be calculated for {symbol}. Cause: {e}")
            return None

    # async def calculate_ema_slope(self, symbol, timerange, length):
    #     result = "none"
    #     try:
    #         df_raw = await self.data.get_data_for_pair(symbol, timerange, length)
    #         df = self.data.resample_data(df_raw, timerange)
    #         ema = talib.EMA(df["close"], timeperiod=length)
    #         ema_slope = ema.diff()
    #         ema_last_slope = ema_slope.dropna().iloc[-1]
    #         if ema_last_slope:
    #             if ema_last_slope > 0:
    #                 categories = "upward"
    #             elif ema_last_slope < 0:
    #                 categories = "downward"
    #             else:
    #                 categories = "flat"
    #         result = categories
    #     except Exception as e:
    #         logging.error(f"EMA SLOPE cannot be calculated for {symbol}. Cause: {e}")
    #     return result

    # async def calculate_ema_distance(self, symbol, timerange, length):
    #     result = False
    #     try:
    #         df_raw = await self.data.get_data_for_pair(symbol, timerange, length)
    #         df = self.data.resample_data(df_raw, timerange)
    #         ema = talib.EMA(df["close"], timeperiod=length)
    #         ema = ema.dropna().iloc[-1]
    #         close_price = df["close"].dropna().iloc[-1]
    #         percentage_diff = abs(close_price - ema) / ema * 100
    #         logging.debug(
    #             f"close_price: {close_price}, ema: {ema}, percentage diff: {percentage_diff}"
    #         )
    #         if percentage_diff < 2:
    #             result = True
    #     except Exception as e:
    #         logging.error(f"EMA Distance cannot be calculated for {symbol}. Cause: {e}")
    #     return result

    # async def calculate_ema_cross(self, symbol, timerange):
    #     result = "none"
    #     try:
    #         df_raw = await self.data.get_data_for_pair(symbol, timerange, 21)
    #         df = self.data.resample_data(df_raw, timerange)
    #         df["ema_short"] = talib.EMA(df["close"], timeperiod=9)
    #         df["ema_long"] = talib.EMA(df["close"], timeperiod=21)
    #         df.dropna(subset=["ema_short", "ema_long"], inplace=True)

    #         if (
    #             df.iloc[-2]["ema_short"] <= df.iloc[-2]["ema_long"]
    #             and df.iloc[-1]["ema_short"] >= df.iloc[-1]["ema_long"]
    #         ):
    #             result = "up"
    #         elif (
    #             df.iloc[-2]["ema_short"] >= df.iloc[-2]["ema_long"]
    #             and df.iloc[-1]["ema_short"] <= df.iloc[-1]["ema_long"]
    #         ):
    #             result = "down"
    #         else:
    #             result = "none"

    #     except Exception as e:
    #         logging.error(f"EMA Cross cannot be calculated for {symbol}. Cause: {e}")

    #     return result

    # async def calculate_rsi(self, symbol, timerange, length):
    #     try:
    #         df_raw = await self.data.get_data_for_pair(symbol, timerange, length)
    #         df = self.data.resample_data(df_raw, timerange)
    #         rsi = talib.RSI(df["close"], timeperiod=length).dropna().iloc[-1]
    #     except Exception as e:
    #         logging.error("Error getting RSI self.data. Cause: {e}")
    #         return None
    #     return rsi

    # async def calculate_rsi_slope(self, symbol, timerange, length):
    #     result = "none"
    #     try:
    #         df_raw = await self.data.get_data_for_pair(symbol, timerange, length)
    #         df = self.data.resample_data(df_raw, timerange)
    #         rsi = talib.RSI(df["close"], timeperiod=length)
    #         rsi_slope = rsi.diff()
    #         rsi_last_slope = rsi_slope.dropna().iloc[-1]
    #         categories = "flat"
    #         if rsi_last_slope:
    #             if rsi_last_slope > 0:
    #                 categories = "upward"
    #             elif rsi_last_slope < 0:
    #                 categories = "downward"
    #         result = categories
    #     except Exception as e:
    #         logging.error(f"RSI SLOPE cannot be calculated for {symbol}. Cause: {e}")
    #     return result

    # async def calculate_24h_volume(self, symbol):
    #     result = "none"
    #     try:
    #         df_raw = await self.data.get_data_for_pair(symbol, "1D", 1)
    #         df = self.data.resample_data(df_raw, "1h").rolling(window=24).mean()
    #         quote_volume = df.apply(lambda row: (row["close"] * row["volume"]), axis=1)
    #         result = quote_volume.sum()
    #     except Exception as e:
    #         logging.error(f"24h volume cannot be calculated for {symbol}. Cause: {e}")
    #     return result

    # @cached(cache=TTLCache(maxsize=1024, ttl=10))
    # async def calculate_btc_pulse(self, currency, timerange):
    #     result = True
    #     try:
    #         symbol = "BTC" + "/" + currency
    #         df_raw = await self.data.get_data_for_pair(symbol, timerange, 50)
    #         df = self.data.resample_data(df_raw, timerange)
    #         df["ema_9"] = talib.EMA(df["close"], timeperiod=9)
    #         df["ema_50"] = talib.EMA(df["close"], timeperiod=50)
    #         ema9 = df["ema_9"].dropna().iloc[-1]
    #         ema50 = df["ema_50"].dropna().iloc[-1]
    #         price_action = (np.log(df["close"].pct_change(3) + 1)) * 100
    #         price_action = price_action.dropna().iloc[-1]

    #         if (price_action < -1) or (ema50 > ema9):
    #             result = False
    #         else:
    #             result = True
    #     except Exception as e:
    #         logging.error(
    #             f"BTC Pulse cannot be calculated, because we don't have enough history self.data. Cause: {e}"
    #         )

    #     return result

    # async def calculate_ichimoku_cross(self, symbol, timerange):
    #     result = "none"
    #     try:
    #         # Data
    #         df_raw = await self.data.get_data_for_pair(symbol, timerange, 200)
    #         df = self.data.resample_data(df_raw, timerange)

    #         # Tenkan Sen (Conversation line)
    #         tenkan_sen_length = 20
    #         tenkan_sen_high = df["high"].rolling(tenkan_sen_length).max()
    #         tenkan_sen_low = df["low"].rolling(tenkan_sen_length).min()
    #         df["tenkan_sen"] = (tenkan_sen_high + tenkan_sen_low) / 2

    #         # Kijun Sen (Base Line)
    #         kijun_sen_length = 60
    #         kijun_sen_high = df["high"].rolling(kijun_sen_length).max()
    #         kijun_sen_low = df["low"].rolling(kijun_sen_length).min()
    #         df["kijun_sen"] = (kijun_sen_high + kijun_sen_low) / 2

    #         # Senkou Span A (Leading Span A)
    #         senkou_span_a_ahead = 30
    #         df["senkou_span_a"] = ((df["tenkan_sen"] + df["kijun_sen"]) / 2).shift(
    #             senkou_span_a_ahead
    #         )
    #         # df["senkou_span_a"] = (df["tenkan_sen"] + df["kijun_sen"]) / 2

    #         # Senkou Span B (Leading Span B)
    #         senkou_span_b_length = 120
    #         senkou_span_b_ahead = 30
    #         senkou_span_b_high = df["high"].rolling(senkou_span_b_length).max()
    #         senkou_span_b_low = df["low"].rolling(senkou_span_b_length).min()
    #         df["senkou_span_b"] = ((senkou_span_b_high + senkou_span_b_low) / 2).shift(
    #             senkou_span_b_ahead
    #         )
    #         # df["senkou_span_b"] = (senkou_span_b_high + senkou_span_b_low) / 2

    #         # Conditions
    #         cond1 = (df["kijun_sen"] > df["senkou_span_a"]) & (
    #             df["kijun_sen"] > df["senkou_span_b"]
    #         )
    #         cond2 = df["tenkan_sen"] > df["kijun_sen"]
    #         cond3 = df["close"] > df["tenkan_sen"]

    #         # All conditions now
    #         all_now = cond1 & cond2 & cond3

    #         # All conditions previous
    #         all_prev = all_now.shift(1).fillna(False).astype(bool)

    #         # Trigger only when going from False → True
    #         df["signal"] = all_now & (~all_prev)

    #         if df["signal"].iloc[-1]:
    #             if (
    #                 df["kijun_sen"].iloc[-2] < df["senkou_span_a"].iloc[-2]
    #                 or df["kijun_sen"].iloc[-2] < df["senkou_span_b"].iloc[-2]
    #             ):
    #                 logging.debug("Buy signal")
    #             result = "up"

    #         logging.debug(
    #             f"Base Line: {df['kijun_sen'].iloc[-1]} Conversation Line: {df['tenkan_sen'].iloc[-1]} Leading Span A: {df['senkou_span_a'].iloc[-1]} Leading Span B: {df['senkou_span_b'].iloc[-1]} Signal: {df['signal'].iloc[-1]}"
    #         )

    #     except Exception as e:
    #         logging.error(
    #             f"Ichimoku Cross cannot be calculated for {symbol}. Cause: {e}"
    #         )
    #     return result
