"""ATH retrieval and caching service."""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import helper
import model
from service.config import resolve_history_lookback_days
from service.exchange import Exchange

logging = helper.LoggerFactory.get_logger("logs/ath.log", "ath")


class AthService:
    """Fetch and cache ATH values for configurable lookback windows."""

    SUPPORTED_TIMEFRAMES = {"4h", "1d", "1w"}

    def __init__(self) -> None:
        """Initialize ATH service resources."""
        self.exchange = Exchange()
        self._cache: dict[tuple[str, str], tuple[float, float]] = {}

    def _to_utc_aware(self, value: datetime) -> datetime:
        """Normalize datetime values to UTC-aware for safe comparisons."""
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def normalize_lookback(self, config: dict[str, Any]) -> tuple[str, int, str]:
        """Normalize configurable lookback and timeframe settings.

        Returns:
            (timeframe, lookback_days, cache_window_key)
        """
        timeframe = (
            str(config.get("dynamic_dca_ath_timeframe", "4h") or "4h").strip().lower()
        )

        if timeframe not in self.SUPPORTED_TIMEFRAMES:
            timeframe = "4h"

        lookback_days = resolve_history_lookback_days(config, timeframe=timeframe)
        cache_window_key = f"{lookback_days}d@{timeframe}"
        return timeframe, lookback_days, cache_window_key

    async def get_recent_ath(
        self,
        symbol: str,
        config: dict[str, Any],
        cache_ttl_seconds: int = 60,
    ) -> tuple[float, str]:
        """Get recent ATH for symbol from cache or exchange.

        Args:
            symbol: Trading pair symbol (e.g. BTC/USDT).
            config: Runtime configuration used by Exchange.
            cache_ttl_seconds: TTL for in-memory and DB cache freshness.

        Returns:
            Tuple of (ath_value, normalized_cache_window_key).
        """
        timeframe, lookback_days, window = self.normalize_lookback(config)
        ttl = max(int(cache_ttl_seconds), 5)
        cache_key = (symbol, window)
        now = time.time()

        in_memory = self._cache.get(cache_key)
        if in_memory and in_memory[0] > now:
            return in_memory[1], window

        fresh_after = datetime.now(UTC) - timedelta(seconds=ttl)
        persisted = await model.AthCache.get_or_none(symbol=symbol, window=window)
        if persisted and self._to_utc_aware(persisted.updated_at) >= fresh_after:
            ath = float(persisted.ath)
            self._cache[cache_key] = (now + ttl, ath)
            return ath, window

        ath = await self._fetch_ath_from_exchange(
            symbol=symbol,
            config=config,
            timeframe=timeframe,
            lookback_days=lookback_days,
        )
        if ath <= 0 and persisted:
            ath = float(persisted.ath)

        if ath > 0:
            await model.AthCache.update_or_create(
                symbol=symbol,
                window=window,
                defaults={
                    "ath": ath,
                    "source_timeframe": timeframe,
                    "window_days": lookback_days,
                },
            )

        self._cache[cache_key] = (now + ttl, ath)
        return ath, window

    async def _fetch_ath_from_exchange(
        self,
        symbol: str,
        config: dict[str, Any],
        timeframe: str,
        lookback_days: int,
    ) -> float:
        """Fetch ATH from exchange OHLCV data for a configured window."""
        since = int((datetime.now() - timedelta(days=lookback_days)).timestamp() * 1000)

        try:
            candles = await self.exchange.get_history_for_symbol(
                config=config,
                symbol=symbol,
                timeframe=timeframe,
                limit=500,
                since=since,
            )
        except Exception as exc:  # noqa: BLE001
            logging.error("Failed to fetch ATH candles for %s: %s", symbol, exc)
            return 0.0

        highs = [
            float(candle[2])
            for candle in candles
            if isinstance(candle, list) and len(candle) >= 3
        ]
        if not highs:
            return 0.0
        return max(highs)
