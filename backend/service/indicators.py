"""Indicator calculations based on OHLCV data."""

import asyncio
from typing import Any

import helper
import talib
from service.config import resolve_history_lookback_days
from service.data import Data
from tortoise.exceptions import BaseORMException

logging = helper.LoggerFactory.get_logger("logs/indicators.log", "indicators")
INDICATOR_CALCULATION_EXCEPTIONS = (
    AttributeError,
    BaseORMException,
    IndexError,
    KeyError,
    RuntimeError,
    TypeError,
    ValueError,
)


class Indicators:
    """Compute technical indicators used by strategies."""

    def __init__(self, data: Any | None = None) -> None:
        """Initialize indicators with optional data source override.

        Args:
            data: Optional data source. When provided, used instead of live
                 `Data()` for all indicator lookups. Used by backtest to inject
                 in-memory OHLCV data without hitting the DB.
        """
        self.data = data if data is not None else Data()
        self._ema_cache: dict[
            tuple[str, str, tuple[int, ...]], tuple[float | None, dict[str, Any]]
        ] = {}
        self._ema_series_cache: dict[tuple[str, str, int], tuple[float | None, Any]] = (
            {}
        )
        self._rsi_series_cache: dict[tuple[str, str, int], tuple[float | None, Any]] = (
            {}
        )
        self._bollinger_series_cache: dict[
            tuple[str, str, int, float], tuple[float | None, dict[str, Any]]
        ] = {}
        self._macd_series_cache: dict[
            tuple[str, str, int, int, int], tuple[float | None, dict[str, Any]]
        ] = {}
        self._close_cache: dict[tuple[str, str, int], tuple[float | None, Any]] = {}
        self._low_cache: dict[tuple[str, str, int], tuple[float | None, Any]] = {}
        self._high_cache: dict[tuple[str, str, int], tuple[float | None, Any]] = {}

    @staticmethod
    def _log_indicator_error(name: str, symbol: str, exc: Exception) -> None:
        """Log indicator calculation failures consistently."""
        logging.error("%s cannot be calculated for %s. Cause: %s", name, symbol, exc)

    @staticmethod
    def _calculate_ema_sync(df: Any, lengths: list[int]) -> dict[str, Any]:
        """Compute EMA values synchronously from a candle DataFrame."""
        ema: dict[str, Any] = {}
        for length in lengths:
            length_key = f"ema_{str(length)}"
            ema[length_key] = (
                talib.EMA(df["close"], timeperiod=length).dropna().iloc[-1]
            )
        return ema

    @staticmethod
    def _calculate_btc_pulse_sync(df: Any) -> bool:
        """Compute BTC pulse trend synchronously from a resampled DataFrame."""
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

        return not (momentum_3 < -1.0 or ema50 > ema9)

    @staticmethod
    def _calculate_rsi_sync(df: Any, length: int) -> float | None:
        """Compute RSI synchronously from a resampled DataFrame."""
        if df is None or df.empty:
            return None
        rsi = talib.RSI(df["close"], timeperiod=length).dropna()
        if rsi.empty:
            return None
        return float(rsi.iloc[-1])

    @staticmethod
    def _calculate_bollinger_bands_sync(
        df: Any, length: int, standard_deviations: float
    ) -> dict[str, float] | None:
        """Compute latest Bollinger Band values from a candle DataFrame."""
        if df is None or df.empty:
            return None
        upper, middle, lower = talib.BBANDS(
            df["close"],
            timeperiod=length,
            nbdevup=standard_deviations,
            nbdevdn=standard_deviations,
            matype=0,
        )
        if upper.dropna().empty or middle.dropna().empty or lower.dropna().empty:
            return None
        middle_value = float(middle.dropna().iloc[-1])
        upper_value = float(upper.dropna().iloc[-1])
        lower_value = float(lower.dropna().iloc[-1])
        bandwidth = (
            ((upper_value - lower_value) / middle_value) * 100 if middle_value else 0.0
        )
        return {
            "upper": upper_value,
            "middle": middle_value,
            "lower": lower_value,
            "bandwidth": bandwidth,
        }

    @staticmethod
    def _calculate_macd_sync(
        df: Any, fast_period: int, slow_period: int, signal_period: int
    ) -> dict[str, float] | None:
        """Compute latest MACD values from a candle DataFrame."""
        if df is None or df.empty:
            return None
        macd, signal, histogram = talib.MACD(
            df["close"],
            fastperiod=fast_period,
            slowperiod=slow_period,
            signalperiod=signal_period,
        )
        if macd.dropna().empty or signal.dropna().empty or histogram.dropna().empty:
            return None
        return {
            "macd": float(macd.dropna().iloc[-1]),
            "signal": float(signal.dropna().iloc[-1]),
            "histogram": float(histogram.dropna().iloc[-1]),
        }

    @staticmethod
    def _calculate_24h_volume_sync(df: Any) -> float | None:
        """Compute 24h quote volume synchronously from hourly candles."""
        if df is None or df.empty:
            return None
        recent = df.dropna().tail(24)
        if recent.empty:
            return None
        quote_volume = (recent["close"] * recent["volume"]).sum()
        return float(quote_volume)

    @staticmethod
    def _calculate_atr_regime_sync(
        df: Any,
        length: int,
        low_k: float,
        mid_k: float,
        high_k: float,
    ) -> tuple[float, dict[str, float | str]]:
        """Compute ATR volatility regime synchronously from candles."""
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
            df = await asyncio.to_thread(self.data.resample_data, df_raw, timerange)
            ema = await asyncio.to_thread(self._calculate_ema_sync, df, lengths)
            self._ema_cache[cache_key] = (latest_timestamp, ema)
        except INDICATOR_CALCULATION_EXCEPTIONS as e:
            self._log_indicator_error("EMA", symbol, e)
            if cached:
                return cached[1]
        return ema

    async def calculate_ema_series(
        self, symbol: str, timerange: str, length: int
    ) -> Any:
        """Return a cached EMA series for candle-indexed replay paths."""
        cache_key = (symbol, timerange, int(length))
        latest_timestamp = await self.data.get_latest_timestamp_for_pair(symbol)
        cached = self._ema_series_cache.get(cache_key)
        if cached and cached[0] == latest_timestamp:
            return cached[1]

        try:
            df_raw = await self._get_indicator_source_data(
                symbol, timerange, max(length * 2, 200)
            )
            df = await asyncio.to_thread(self.data.resample_data, df_raw, timerange)
            series = await asyncio.to_thread(
                lambda: talib.EMA(df["close"].dropna(), timeperiod=length)
            )
            self._ema_series_cache[cache_key] = (latest_timestamp, series)
            return series
        except INDICATOR_CALCULATION_EXCEPTIONS as e:
            self._log_indicator_error("EMA series", symbol, e)
            if cached:
                return cached[1]
            return None

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
            df = await asyncio.to_thread(self.data.resample_data, df_raw, timerange)
            close = df["close"]
            self._close_cache[cache_key] = (latest_timestamp, close)
            return close
        except INDICATOR_CALCULATION_EXCEPTIONS as e:
            self._log_indicator_error("Close price", symbol, e)
            if cached:
                return cached[1]
            return None

    async def get_low_price(self, symbol: str, timerange: str, length: int) -> Any:
        """Return low price series for wick-based strategy conditions."""
        cache_key = (symbol, timerange, length)
        latest_timestamp = await self.data.get_latest_timestamp_for_pair(symbol)
        cached = self._low_cache.get(cache_key)
        if cached and cached[0] == latest_timestamp:
            return cached[1]

        try:
            df_raw = await self._get_indicator_source_data(
                symbol, timerange, max(length * 2, 50)
            )
            df = await asyncio.to_thread(self.data.resample_data, df_raw, timerange)
            low = df["low"]
            self._low_cache[cache_key] = (latest_timestamp, low)
            return low
        except INDICATOR_CALCULATION_EXCEPTIONS as e:
            self._log_indicator_error("Low price", symbol, e)
            if cached:
                return cached[1]
            return None

    async def get_high_price(self, symbol: str, timerange: str, length: int) -> Any:
        """Return high price series for wick-based strategy conditions."""
        cache_key = (symbol, timerange, length)
        latest_timestamp = await self.data.get_latest_timestamp_for_pair(symbol)
        cached = self._high_cache.get(cache_key)
        if cached and cached[0] == latest_timestamp:
            return cached[1]

        try:
            df_raw = await self._get_indicator_source_data(
                symbol, timerange, max(length * 2, 50)
            )
            df = await asyncio.to_thread(self.data.resample_data, df_raw, timerange)
            high = df["high"]
            self._high_cache[cache_key] = (latest_timestamp, high)
            return high
        except INDICATOR_CALCULATION_EXCEPTIONS as e:
            self._log_indicator_error("High price", symbol, e)
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
            df = await asyncio.to_thread(self.data.resample_data, df_raw, timerange)
            result = await asyncio.to_thread(self._calculate_btc_pulse_sync, df)
        except INDICATOR_CALCULATION_EXCEPTIONS as e:
            self._log_indicator_error("BTC Pulse", symbol, e)
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
            df = await asyncio.to_thread(self.data.resample_data, df_raw, timerange)
            return await asyncio.to_thread(self._calculate_rsi_sync, df, length)
        except INDICATOR_CALCULATION_EXCEPTIONS as e:
            self._log_indicator_error("RSI", symbol, e)
            return None

    async def calculate_rsi_series(
        self, symbol: str, timerange: str, length: int = 14
    ) -> Any:
        """Return a cached RSI series for runtime and candle-indexed replay."""
        cache_key = (symbol, timerange, int(length))
        latest_timestamp = await self.data.get_latest_timestamp_for_pair(symbol)
        cached = self._rsi_series_cache.get(cache_key)
        if cached and cached[0] == latest_timestamp:
            return cached[1]

        try:
            df_raw = await self._get_indicator_source_data(
                symbol, timerange, max(length * 3, 50)
            )
            df = await asyncio.to_thread(self.data.resample_data, df_raw, timerange)
            series = await asyncio.to_thread(
                lambda: talib.RSI(df["close"].dropna(), timeperiod=length)
            )
            self._rsi_series_cache[cache_key] = (latest_timestamp, series)
            return series
        except INDICATOR_CALCULATION_EXCEPTIONS as e:
            self._log_indicator_error("RSI series", symbol, e)
            if cached:
                return cached[1]
            return None

    async def calculate_bollinger_bands(
        self,
        symbol: str,
        timerange: str,
        length: int = 20,
        standard_deviations: float = 2.0,
    ) -> dict[str, float] | None:
        """Calculate latest Bollinger Band values and bandwidth percent."""
        series = await self.calculate_bollinger_bands_series(
            symbol,
            timerange,
            length,
            standard_deviations,
        )
        try:
            upper = float(series["upper"].dropna().iloc[-1])
            middle = float(series["middle"].dropna().iloc[-1])
            lower = float(series["lower"].dropna().iloc[-1])
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return None
        return {
            "upper": upper,
            "middle": middle,
            "lower": lower,
            "bandwidth": (((upper - lower) / middle) * 100 if middle else 0.0),
        }

    async def calculate_bollinger_bands_series(
        self,
        symbol: str,
        timerange: str,
        length: int = 20,
        standard_deviations: float = 2.0,
    ) -> dict[str, Any] | None:
        """Return cached Bollinger Band and bandwidth series."""
        cache_key = (
            symbol,
            timerange,
            int(length),
            float(standard_deviations),
        )
        latest_timestamp = await self.data.get_latest_timestamp_for_pair(symbol)
        cached = self._bollinger_series_cache.get(cache_key)
        if cached and cached[0] == latest_timestamp:
            return cached[1]

        try:
            df_raw = await self._get_indicator_source_data(
                symbol, timerange, max(length * 3, 50)
            )
            df = await asyncio.to_thread(self.data.resample_data, df_raw, timerange)

            def _build_series() -> dict[str, Any]:
                upper, middle, lower = talib.BBANDS(
                    df["close"].dropna(),
                    timeperiod=length,
                    nbdevup=standard_deviations,
                    nbdevdn=standard_deviations,
                    matype=0,
                )
                bandwidth = ((upper - lower) / middle) * 100
                return {
                    "upper": upper,
                    "middle": middle,
                    "lower": lower,
                    "bandwidth": bandwidth,
                }

            series = await asyncio.to_thread(_build_series)
            self._bollinger_series_cache[cache_key] = (latest_timestamp, series)
            return series
        except INDICATOR_CALCULATION_EXCEPTIONS as e:
            self._log_indicator_error("Bollinger Bands series", symbol, e)
            if cached:
                return cached[1]
            return None

    async def calculate_macd(
        self,
        symbol: str,
        timerange: str,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> dict[str, float] | None:
        """Calculate latest MACD line, signal line, and histogram values."""
        series = await self.calculate_macd_series(
            symbol,
            timerange,
            fast_period,
            slow_period,
            signal_period,
        )
        try:
            return {
                "macd": float(series["macd"].dropna().iloc[-1]),
                "signal": float(series["signal"].dropna().iloc[-1]),
                "histogram": float(series["histogram"].dropna().iloc[-1]),
            }
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return None

    async def calculate_macd_series(
        self,
        symbol: str,
        timerange: str,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> dict[str, Any] | None:
        """Return cached MACD series for runtime and candle-indexed replay."""
        cache_key = (
            symbol,
            timerange,
            int(fast_period),
            int(slow_period),
            int(signal_period),
        )
        latest_timestamp = await self.data.get_latest_timestamp_for_pair(symbol)
        cached = self._macd_series_cache.get(cache_key)
        if cached and cached[0] == latest_timestamp:
            return cached[1]

        try:
            df_raw = await self._get_indicator_source_data(
                symbol, timerange, max(slow_period * 3, 100)
            )
            df = await asyncio.to_thread(self.data.resample_data, df_raw, timerange)

            def _build_series() -> dict[str, Any]:
                macd, signal, histogram = talib.MACD(
                    df["close"].dropna(),
                    fastperiod=fast_period,
                    slowperiod=slow_period,
                    signalperiod=signal_period,
                )
                return {"macd": macd, "signal": signal, "histogram": histogram}

            series = await asyncio.to_thread(_build_series)
            self._macd_series_cache[cache_key] = (latest_timestamp, series)
            return series
        except INDICATOR_CALCULATION_EXCEPTIONS as e:
            self._log_indicator_error("MACD series", symbol, e)
            if cached:
                return cached[1]
            return None

    async def calculate_24h_volume(self, symbol: str) -> float | None:
        """Calculate approximate quote-volume over the latest 24 hours."""
        try:
            # Pull enough candles and aggregate to 1h to derive a stable 24h volume.
            df_raw = await self.data.get_data_for_pair(symbol, "1m", 1500)
            if df_raw is None:
                return None
            df = await asyncio.to_thread(self.data.resample_data, df_raw, "1h")
            return await asyncio.to_thread(self._calculate_24h_volume_sync, df)
        except INDICATOR_CALCULATION_EXCEPTIONS as e:
            self._log_indicator_error("24h volume", symbol, e)
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

            df = await asyncio.to_thread(self.data.resample_data, df_raw, timerange)
            return await asyncio.to_thread(
                self._calculate_atr_regime_sync,
                df,
                length,
                low_k,
                mid_k,
                high_k,
            )
        except INDICATOR_CALCULATION_EXCEPTIONS as e:
            self._log_indicator_error("ATR regime", symbol, e)
            return 1.0, {"regime": "mid", "atr_percent": 0.0}
