"""Indicator calculations based on OHLCV data."""

from typing import Any

import helper
import talib
from service.config import resolve_history_lookback_days
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

    async def _get_indicator_source_data(
        self, symbol: str, timerange: str, minimum_length: int
    ) -> Any:
        """Load stable source candles for indicator calculations.

        Prefer timeframe-based lookback windows to keep long EMAs stable (e.g. EMA200 on 4h),
        then fall back to length-based retrieval if needed.
        """
        lookback_days = resolve_history_lookback_days({"timeframe": timerange})
        df_raw = await self.data.get_data_for_pair_by_days(symbol, lookback_days)
        if df_raw is None or df_raw.empty:
            return await self.data.get_data_for_pair(symbol, timerange, minimum_length)
        return df_raw

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
            df_raw = await self._get_indicator_source_data(
                symbol, timerange, max(max_length * 2, 200)
            )
            df = self.data.resample_data(df_raw, timerange)
            for length in lengths:
                length_key = f"ema_{str(length)}"
                ema[length_key] = (
                    talib.EMA(df["close"], timeperiod=length).dropna().iloc[-2]
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
            df_raw = await self._get_indicator_source_data(
                symbol, timerange, max(length * 2, 50)
            )
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
        config: dict[str, Any] | None = None,
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
            if config:
                lookback_days = resolve_history_lookback_days(
                    config, timeframe=timerange
                )
                df_raw = await self.data.get_data_for_pair_by_days(
                    symbol, lookback_days
                )
            else:
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

    async def calculate_ema_cross(self, symbol: str, timerange: str) -> str:
        """Calculate EMA(9/21) cross direction for a symbol."""
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
