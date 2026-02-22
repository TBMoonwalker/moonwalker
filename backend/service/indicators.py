"""Indicator calculations based on OHLCV data."""

from typing import Any

import helper
import talib
from service.data import Data

logging = helper.LoggerFactory.get_logger("logs/indicators.log", "indicators")


class Indicators:
    """Compute technical indicators used by strategies."""

    def __init__(self) -> None:
        self.data = Data()
        self._ema_cache: dict[
            tuple[str, str, tuple[int, ...]], tuple[float | None, dict[str, Any]]
        ] = {}
        self._close_cache: dict[tuple[str, str, int], tuple[float | None, Any]] = {}

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
        cache_key = (symbol, timerange, tuple(lengths))
        latest_timestamp = await self.data.get_latest_timestamp_for_pair(symbol)
        cached = self._ema_cache.get(cache_key)
        if cached and cached[0] == latest_timestamp:
            return cached[1]

        ema = {}
        try:
            max_length = max(lengths)
            df_raw = await self.data.get_data_for_pair(symbol, timerange, max_length)
            df = self.data.resample_data(df_raw, timerange)
            for length in lengths:
                length_key = f"ema_{str(length)}"
                ema[length_key] = (
                    talib.EMA(df["close"], timeperiod=length).dropna().iloc[-1]
                )
            self._ema_cache[cache_key] = (latest_timestamp, ema)
        except Exception as e:
            # Broad catch to avoid breaking strategy execution.
            logging.error(f"EMA cannot be calculated for {symbol}. Cause: {e}")
            if cached:
                return cached[1]
        return ema

    async def get_close_price(self, symbol: str, timerange: str, length: int) -> Any:
        """Return close price series for a symbol."""
        cache_key = (symbol, timerange, length)
        latest_timestamp = await self.data.get_latest_timestamp_for_pair(symbol)
        cached = self._close_cache.get(cache_key)
        if cached and cached[0] == latest_timestamp:
            return cached[1]

        try:
            df_raw = await self.data.get_data_for_pair(symbol, timerange, length)
            df = self.data.resample_data(df_raw, timerange)
            close = df["close"]
            self._close_cache[cache_key] = (latest_timestamp, close)
            return close
        except Exception as e:
            # Broad catch to avoid breaking strategy execution.
            logging.error(f"Close price cannot be calculated for {symbol}. Cause: {e}")
            if cached:
                return cached[1]
            return None

    async def calculate_btc_pulse(self, currency: str, timerange: str) -> bool:
        """Return BTC pulse trend state for the configured quote currency.

        The signal is considered bearish when short-term momentum is strongly
        negative or EMA50 is above EMA9.
        """
        result = True
        symbol = f"BTC/{currency}"
        try:
            df_raw = await self.data.get_data_for_pair(symbol, timerange, 60)
            df = self.data.resample_data(df_raw, timerange)
            if df is None or df.empty:
                return True

            close = df["close"].dropna()
            if close.empty:
                return True

            ema9_series = talib.EMA(close, timeperiod=9).dropna()
            ema50_series = talib.EMA(close, timeperiod=50).dropna()
            if ema9_series.empty or ema50_series.empty:
                return True

            ema9 = float(ema9_series.iloc[-1])
            ema50 = float(ema50_series.iloc[-1])

            momentum_3 = 0.0
            if len(close) >= 4:
                current_close = float(close.iloc[-1])
                past_close = float(close.iloc[-4])
                if past_close != 0:
                    momentum_3 = ((current_close - past_close) / past_close) * 100

            result = not (momentum_3 < -1.0 or ema50 > ema9)
        except Exception as e:
            logging.error("BTC Pulse cannot be calculated for %s. Cause: %s", symbol, e)
            result = True

        return result

    async def calculate_rsi(
        self, symbol: str, timerange: str, length: int
    ) -> float | None:
        """Calculate RSI for the latest candle."""
        try:
            df_raw = await self.data.get_data_for_pair(symbol, timerange, length)
            if df_raw is None:
                return None
            df = self.data.resample_data(df_raw, timerange)
            if df is None or df.empty:
                return None
            rsi = talib.RSI(df["close"], timeperiod=length).dropna()
            if rsi.empty:
                return None
            return float(rsi.iloc[-1])
        except Exception as e:
            logging.error(f"RSI cannot be calculated for {symbol}. Cause: {e}")
            return None

    async def calculate_24h_volume(self, symbol: str) -> float | None:
        """Calculate approximate quote-volume over the latest 24 hours."""
        try:
            # Pull enough candles and aggregate to 1h to derive a stable 24h volume.
            df_raw = await self.data.get_data_for_pair(symbol, "1m", 1500)
            if df_raw is None:
                return None
            df = self.data.resample_data(df_raw, "1h")
            if df is None or df.empty:
                return None

            recent = df.dropna().tail(24)
            if recent.empty:
                return None

            quote_volume = (recent["close"] * recent["volume"]).sum()
            return float(quote_volume)
        except Exception as e:
            logging.error(f"24h volume cannot be calculated for {symbol}. Cause: {e}")
            return None

    async def calculate_atr_regime_multiplier(
        self,
        symbol: str,
        timerange: str,
        length: int = 14,
        low_k: float = 2.2,
        mid_k: float = 1.8,
        high_k: float = 1.4,
    ) -> tuple[float, dict[str, float | str]]:
        """Return ATR-based volatility regime multiplier.

        The regime uses ATR as percent of close price and maps to:
        - LOW  -> 0.75
        - MID  -> 1.0
        - HIGH -> 1.5
        """
        try:
            df_raw = await self.data.get_data_for_pair(
                symbol, timerange, max(length * 8, 80)
            )
            if df_raw is None:
                return 1.0, {"regime": "mid", "atr_percent": 0.0}

            df = self.data.resample_data(df_raw, timerange)
            if df is None or df.empty:
                return 1.0, {"regime": "mid", "atr_percent": 0.0}

            atr_series = talib.ATR(
                df["high"], df["low"], df["close"], timeperiod=max(2, int(length))
            ).dropna()
            close_series = df["close"].dropna()
            if atr_series.empty or close_series.empty:
                return 1.0, {"regime": "mid", "atr_percent": 0.0}

            atr_value = float(atr_series.iloc[-1])
            close_value = float(close_series.iloc[-1])
            if close_value <= 0:
                return 1.0, {"regime": "mid", "atr_percent": 0.0}

            atr_percent = (atr_value / close_value) * 100
            if atr_percent <= float(high_k):
                regime = "low"
                multiplier = 0.75
            elif atr_percent <= float(mid_k):
                regime = "mid"
                multiplier = 1.0
            elif atr_percent <= float(low_k):
                regime = "high"
                multiplier = 1.5
            else:
                regime = "high"
                multiplier = 1.5

            return multiplier, {
                "regime": regime,
                "atr_percent": round(atr_percent, 6),
                "low_k": float(low_k),
                "mid_k": float(mid_k),
                "high_k": float(high_k),
            }
        except Exception as e:
            logging.error(
                "ATR regime cannot be calculated for %s. Cause: %s", symbol, e
            )
            return 1.0, {"regime": "mid", "atr_percent": 0.0}

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

    async def calculate_ema_cross(self, symbol, timerange):
        result = "none"
        try:
            df_raw = await self.data.get_data_for_pair(symbol, timerange, 21)
            df = self.data.resample_data(df_raw, timerange)
            df["ema_short"] = talib.EMA(df["close"], timeperiod=9)
            df["ema_long"] = talib.EMA(df["close"], timeperiod=21)
            df.dropna(subset=["ema_short", "ema_long"], inplace=True)

            if (
                df.iloc[-2]["ema_short"] <= df.iloc[-2]["ema_long"]
                and df.iloc[-1]["ema_short"] >= df.iloc[-1]["ema_long"]
            ):
                result = "up"
            elif (
                df.iloc[-2]["ema_short"] >= df.iloc[-2]["ema_long"]
                and df.iloc[-1]["ema_short"] <= df.iloc[-1]["ema_long"]
            ):
                result = "down"
            else:
                result = "none"

        except Exception as e:
            logging.error(f"EMA Cross cannot be calculated for {symbol}. Cause: {e}")

        return result

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
