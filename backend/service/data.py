"""Data access helpers for OHLCV and listings."""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import ccxt.async_support as ccxt
import helper
import model
import pandas as pd
from cachetools import TTLCache
from service.config import resolve_timeframe
from service.database import run_sqlite_write_with_retry
from service.exchange import Exchange
from tortoise.exceptions import BaseORMException

logging = helper.LoggerFactory.get_logger("logs/data.log", "data")


class Data:
    """Data retrieval and transformation utilities."""

    SYMBOLS_CACHE_TTL_SECONDS = 300
    LOOKBACK_BUFFER_MULTIPLIER = 2

    def __init__(self, persist_exchange: bool = False) -> None:
        utils = helper.Utils()
        self.exchange = Exchange()
        self.utils = utils
        self.persist_exchange = persist_exchange
        self._symbols_cache: TTLCache[str, list[str]] = TTLCache(
            maxsize=64, ttl=self.SYMBOLS_CACHE_TTL_SECONDS
        )

    async def close(self) -> None:
        """Close the underlying exchange client."""
        await self.exchange.close()

    async def get_listing_date(
        self, config: dict[str, Any], symbol: str
    ) -> datetime | None:
        """Fetch the listing date of a token, using SQLite cache."""
        # Check cache first
        listing = await model.Listings.get_or_none(symbol=symbol)
        if listing:
            return listing.listing_date

        # If not cached -> fetch from exchange
        try:
            ohlcv = await self.exchange.get_history_for_symbol(
                config, symbol, timeframe="1d"
            )
            if not ohlcv:
                logging.error("No OHLCV data available for %s", symbol)
            else:
                first_timestamp = ohlcv[0][0]
                listing_date = datetime.fromtimestamp(
                    first_timestamp / 1000, tz=timezone.utc
                )

                # Save to DB cache
                await run_sqlite_write_with_retry(
                    lambda: model.Listings.create(
                        symbol=symbol, listing_date=listing_date
                    ),
                    f"storing listing date for {symbol}",
                )
                return listing_date
        except (
            BaseORMException,
            ccxt.ExchangeError,
            ccxt.NetworkError,
            ccxt.BaseError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            logging.error("Error fetching OHLCV for %s: %s", symbol, e)
        finally:
            if not self.persist_exchange:
                await self.exchange.close()

        return None

    async def is_token_old_enough(self, config: dict[str, Any], symbol: str) -> bool:
        """Return False if token is newer than threshold_days, True otherwise."""
        threshold_days = config.get("pair_age", 30)
        listing_date = await self.get_listing_date(config, symbol)
        if listing_date:
            threshold_date = datetime.now(timezone.utc) - timedelta(days=threshold_days)
            return listing_date <= threshold_date
        else:
            return False

    async def get_ticker_symbol_list(self) -> list[str]:
        """Return distinct ticker symbols."""
        symbols = await model.Tickers.all().distinct().values_list("symbol", flat=True)
        return symbols

    async def get_latest_timestamp_for_pair(self, pair: str) -> float | None:
        """Return the latest stored ticker timestamp for a pair."""
        symbol = self.utils.split_symbol(pair)
        row = await model.Tickers.filter(symbol=symbol).order_by("-timestamp").first()
        if row is None:
            return None
        return float(row.timestamp)

    async def get_exchange_symbols_for_currency(
        self, config: dict[str, Any], currency: str
    ) -> list[str]:
        """Return exchange symbols for the given quote currency."""
        cache_key = (
            f"{config.get('exchange','')}:"
            f"{config.get('market','spot')}:"
            f"{bool(config.get('dry_run', True))}:"
            f"{currency.upper()}"
        )
        if cache_key in self._symbols_cache:
            return self._symbols_cache[cache_key]

        try:
            symbols = await self.exchange.get_symbols_for_quote_currency(
                config, currency
            )
            self._symbols_cache[cache_key] = symbols
            return symbols
        except (
            ccxt.ExchangeError,
            ccxt.NetworkError,
            ccxt.BaseError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            logging.error("Error fetching exchange symbols for %s: %s", currency, e)
            return []
        finally:
            if not self.persist_exchange:
                await self.exchange.close()

    def __timeframe_to_seconds(self, timerange: str) -> int:
        """Convert timeframe notation to seconds.

        Supported examples: 1m, 5m, 15min, 1h, 4h, 1d, 1w.
        Falls back to 60 seconds if parsing fails.
        """
        normalized = str(timerange or "").strip().lower()
        if not normalized:
            return 60

        normalized = normalized.replace("min", "m")
        match = re.fullmatch(r"(\d+)\s*([mhdw])", normalized)
        if not match:
            return 60

        value = int(match.group(1))
        unit = match.group(2)
        multipliers = {
            "m": 60,
            "h": 60 * 60,
            "d": 24 * 60 * 60,
            "w": 7 * 24 * 60 * 60,
        }
        return max(1, value) * multipliers[unit]

    def __calculate_min_candle_date(self, timerange: str, length: int) -> int:
        """Calculate earliest timestamp in milliseconds for candle history."""
        timeframe_seconds = self.__timeframe_to_seconds(timerange)
        candles = max(1, int(length))
        lookback_seconds = timeframe_seconds * candles * self.LOOKBACK_BUFFER_MULTIPLIER
        end_time = datetime.now(timezone.utc)
        min_date = end_time - timedelta(seconds=lookback_seconds)
        return int(min_date.timestamp() * 1000)

    def __timeframe_to_milliseconds(self, timerange: str) -> int:
        """Convert timeframe notation to milliseconds."""
        return self.__timeframe_to_seconds(timerange) * 1000

    def __resolve_required_history_window(
        self,
        history_data: int,
        config: dict[str, Any],
        since_ms: int | None = None,
    ) -> tuple[int, int, int]:
        """Return normalized required history window and timeframe size."""
        timeframe = resolve_timeframe(config)
        timeframe_ms = max(1, self.__timeframe_to_milliseconds(timeframe))
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        current_candle_start = now_ms - (now_ms % timeframe_ms)
        required_until = max(0, current_candle_start - timeframe_ms)
        requested_since = (
            int(since_ms)
            if since_ms is not None
            else int(
                (datetime.now(timezone.utc) - timedelta(days=history_data)).timestamp()
                * 1000
            )
        )
        required_since = max(
            0,
            ((requested_since + timeframe_ms - 1) // timeframe_ms) * timeframe_ms,
        )
        if required_since > required_until:
            required_since = required_until
        return required_since, required_until, timeframe_ms

    @staticmethod
    def _build_required_timestamps(
        required_since: int, required_until: int, timeframe_ms: int
    ) -> set[int]:
        """Build the exact timestamp set required for a history window."""
        if timeframe_ms <= 0 or required_until < required_since:
            return set()
        return set(range(required_since, required_until + 1, timeframe_ms))

    @staticmethod
    def _is_complete_since_first_available_candle(
        stored_timestamps: set[int],
        available_since: int | None,
        required_until: int,
        timeframe_ms: int,
    ) -> bool:
        """Return True when history is complete from the first available candle onward."""
        if (
            available_since is None
            or timeframe_ms <= 0
            or required_until < available_since
        ):
            return False
        effective_required = Data._build_required_timestamps(
            available_since,
            required_until,
            timeframe_ms,
        )
        return bool(effective_required) and effective_required.issubset(
            stored_timestamps
        )

    async def __get_stored_timestamps(
        self, symbol: str, since_ms: int, until_ms: int
    ) -> set[int]:
        """Return stored timestamps for a symbol within the required window."""
        rows = (
            await model.Tickers.filter(symbol=symbol)
            .filter(timestamp__gte=since_ms, timestamp__lte=until_ms)
            .values_list("timestamp", flat=True)
        )
        timestamps: set[int] = set()
        for row in rows:
            try:
                timestamps.add(int(float(row)))
            except (TypeError, ValueError):
                continue
        return timestamps

    async def __fetch_and_store_history_range(
        self,
        symbol: str,
        config: dict[str, Any],
        fetch_since_ms: int,
        required_since: int,
        required_until: int,
        required_timestamps: set[int],
        existing_timestamps: set[int],
    ) -> tuple[set[int], set[int]]:
        """Fetch OHLCV from exchange and return fetched and inserted candle timestamps."""
        ohlcv_data = await self.exchange.get_history_for_symbol(
            config,
            symbol,
            resolve_timeframe(config),
            limit=1000,
            since=fetch_since_ms,
        )
        if not ohlcv_data:
            logging.warning(
                "No historical OHLCV candles returned for %s (since=%s).",
                symbol,
                fetch_since_ms,
            )
            return set(), set()

        normalized_symbol = self.utils.split_symbol(symbol)
        rows_to_insert: list[model.Tickers] = []
        fetched_timestamps: set[int] = set()
        inserted_timestamps: set[int] = set()

        for candle in ohlcv_data:
            timestamp = int(candle[0])
            if timestamp < required_since or timestamp > required_until:
                continue
            if timestamp not in required_timestamps:
                continue
            fetched_timestamps.add(timestamp)
            if timestamp in existing_timestamps or timestamp in inserted_timestamps:
                continue

            rows_to_insert.append(
                model.Tickers(
                    timestamp=timestamp,
                    symbol=normalized_symbol,
                    open=candle[1],
                    high=candle[2],
                    low=candle[3],
                    close=candle[4],
                    volume=candle[5],
                )
            )
            inserted_timestamps.add(timestamp)

        if rows_to_insert:
            await run_sqlite_write_with_retry(
                lambda: model.Tickers.bulk_create(rows_to_insert),
                f"bulk insert history for {normalized_symbol}",
            )

        return fetched_timestamps, inserted_timestamps

    @staticmethod
    def _rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
        """Create and sanitize a DataFrame from DB rows."""
        df = pd.DataFrame(rows)
        df.dropna(inplace=True)
        return df

    @staticmethod
    def _append_live_candle(
        df_source: pd.DataFrame, live_candle: dict[str, float | str]
    ) -> pd.DataFrame:
        """Append in-memory live candle data to DB candles."""
        return pd.concat([df_source, pd.DataFrame([live_candle])], ignore_index=True)

    @staticmethod
    def _timestamp_to_unix_seconds(timestamp: Any) -> float | None:
        """Convert arbitrary timestamp-like values to UTC unix seconds."""
        if pd.isna(timestamp):
            return None
        try:
            return pd.Timestamp(timestamp).timestamp()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _serialize_ohlcv_dataframe(df_source: pd.DataFrame, offset: float) -> str:
        """Convert OHLCV DataFrame into frontend payload JSON."""
        df = df_source.copy()
        offset_minutes = int(offset)
        offset_seconds = offset_minutes * 60
        timestamp_series = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df["time"] = timestamp_series.map(Data._timestamp_to_unix_seconds)
        df.dropna(subset=["time"], inplace=True)
        df["time"] = df["time"].astype(float) + float(offset_seconds)
        df.drop_duplicates(subset=["time"], inplace=True)
        df.drop("volume", axis=1, inplace=True)
        df.drop("timestamp", axis=1, inplace=True)
        return df.to_json(orient="records")

    async def count_history_data_for_symbol(self, symbol: str) -> int | bool:
        """Count history data rows for a symbol."""
        try:
            query = await model.Tickers.filter(symbol=f"{symbol}").count()
            logging.debug("Counted %s entries for symbol %s", query, symbol)
            return query
        except BaseORMException as e:
            logging.error("Error counting history data for symbol %s: %s", symbol, e)

        return False

    async def add_history_data_for_symbol(
        self,
        symbol: str,
        history_data: int,
        config: dict[str, Any],
        since_ms: int | None = None,
    ) -> bool:
        """Ensure required history exists for a symbol without deleting stored data."""
        try:
            (
                required_since,
                required_until,
                timeframe_ms,
            ) = self.__resolve_required_history_window(history_data, config, since_ms)
            required_timestamps = self._build_required_timestamps(
                required_since, required_until, timeframe_ms
            )
            if not required_timestamps:
                logging.warning("No closed candle window available yet for %s.", symbol)
                return False

            stored_timestamps = await self.__get_stored_timestamps(
                symbol, required_since, required_until
            )
            if required_timestamps.issubset(stored_timestamps):
                logging.info("History already complete for %s", symbol)
                return True

            fetch_starts: list[int] = []
            if not stored_timestamps:
                fetch_starts.append(required_since)
            else:
                earliest_stored = min(stored_timestamps)
                latest_stored = max(stored_timestamps)
                if earliest_stored > required_since:
                    fetch_starts.append(required_since)
                if latest_stored < required_until:
                    fetch_starts.append(latest_stored + timeframe_ms)

            if not fetch_starts:
                fetch_starts.append(required_since)

            earliest_available_timestamp: int | None = None
            for fetch_since in dict.fromkeys(fetch_starts):
                fetched_timestamps, inserted_timestamps = (
                    await self.__fetch_and_store_history_range(
                        symbol=symbol,
                        config=config,
                        fetch_since_ms=fetch_since,
                        required_since=required_since,
                        required_until=required_until,
                        required_timestamps=required_timestamps,
                        existing_timestamps=stored_timestamps,
                    )
                )
                if fetched_timestamps:
                    fetched_earliest = min(fetched_timestamps)
                    if earliest_available_timestamp is None:
                        earliest_available_timestamp = fetched_earliest
                    else:
                        earliest_available_timestamp = min(
                            earliest_available_timestamp, fetched_earliest
                        )
                stored_timestamps.update(inserted_timestamps)

            if required_timestamps.issubset(stored_timestamps):
                logging.info("Added missing history boundaries for %s", symbol)
                return True

            if self._is_complete_since_first_available_candle(
                stored_timestamps=stored_timestamps,
                available_since=earliest_available_timestamp,
                required_until=required_until,
                timeframe_ms=timeframe_ms,
            ):
                logging.info(
                    "Added history for %s from first available exchange candle at %s",
                    symbol,
                    earliest_available_timestamp,
                )
                return True

            logging.info(
                "History for %s is still incomplete after boundary sync. "
                "Retrying full-window refill without deleting local candles.",
                symbol,
            )
            refill_fetched_timestamps, refill_inserted_timestamps = (
                await self.__fetch_and_store_history_range(
                    symbol=symbol,
                    config=config,
                    fetch_since_ms=required_since,
                    required_since=required_since,
                    required_until=required_until,
                    required_timestamps=required_timestamps,
                    existing_timestamps=stored_timestamps,
                )
            )
            stored_timestamps.update(refill_inserted_timestamps)

            if refill_fetched_timestamps:
                refill_earliest = min(refill_fetched_timestamps)
                if earliest_available_timestamp is None:
                    earliest_available_timestamp = refill_earliest
                else:
                    earliest_available_timestamp = min(
                        earliest_available_timestamp, refill_earliest
                    )

            if required_timestamps.issubset(stored_timestamps):
                logging.info("Added history for %s", symbol)
                return True

            if self._is_complete_since_first_available_candle(
                stored_timestamps=stored_timestamps,
                available_since=earliest_available_timestamp,
                required_until=required_until,
                timeframe_ms=timeframe_ms,
            ):
                logging.info(
                    "Added history for %s from first available exchange candle at %s",
                    symbol,
                    earliest_available_timestamp,
                )
                return True

            missing_count = len(required_timestamps - stored_timestamps)
            logging.error(
                "History for %s remains incomplete after refill attempt. "
                "missing_candles=%s",
                symbol,
                missing_count,
            )
        except (
            BaseORMException,
            ccxt.ExchangeError,
            ccxt.NetworkError,
            ccxt.BaseError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            logging.error("Error adding history for %s. Cause: %s", symbol, e)
        finally:
            if not self.persist_exchange:
                await self.exchange.close()
        return False

    async def __get_dataframe_for_symbol_since(
        self,
        symbol: str,
        start_timestamp: int | float,
        fields: tuple[str, ...] | None = None,
    ) -> pd.DataFrame | None:
        """Return ticker rows for a symbol since a timestamp as a DataFrame."""
        query = model.Tickers.filter(symbol=symbol).filter(
            timestamp__gt=start_timestamp
        )
        rows = (
            await query.order_by("timestamp").values(*fields)
            if fields
            else await query.order_by("timestamp").values()
        )
        if not rows:
            return None
        return await asyncio.to_thread(self._rows_to_dataframe, rows)

    async def get_ohlcv_for_pair(
        self, pair: str, timerange: str, timestamp_start: float, offset: float
    ) -> str | dict[str, Any]:
        """Return OHLCV data for a pair and timerange."""
        # 600000 --> 60 minutes in milliseconds before
        # start_date = datetime.fromtimestamp(((float(timestamp_start) - 600000) / 1000.0),UTC,)
        symbol = self.utils.split_symbol(pair)
        start_timestamp = float(timestamp_start) - 60000
        df_source = await self.__get_dataframe_for_symbol_since(
            symbol,
            start_timestamp,
            fields=("timestamp", "open", "high", "low", "close", "volume"),
        )
        if df_source is None:
            df_source = pd.DataFrame()
        live_candle = self.__get_live_candle_for_symbol(symbol, start_timestamp)
        if live_candle:
            df_source = await asyncio.to_thread(
                self._append_live_candle, df_source, live_candle
            )

        if not df_source.empty:
            df = await asyncio.to_thread(self.resample_data, df_source, timerange)
            if df is not None and not df.empty:
                return await asyncio.to_thread(
                    self._serialize_ohlcv_dataframe, df, offset
                )
        return {}

    def __get_live_candle_for_symbol(
        self, symbol: str, start_timestamp: float
    ) -> dict[str, float | str] | None:
        """Return current in-memory watcher candle for symbol if it is in range."""
        try:
            from service.watcher import Watcher

            live = Watcher.candles.get(symbol)
            if not live or len(live) < 6:
                return None
            if float(live[0]) <= float(start_timestamp):
                return None
            return {
                "timestamp": float(live[0]),
                "symbol": symbol,
                "open": float(live[1]),
                "high": float(live[2]),
                "low": float(live[3]),
                "close": float(live[4]),
                "volume": float(live[5]),
            }
        except (
            ImportError,
            AttributeError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ):
            return None

    async def get_data_for_pair(
        self, pair: str, timerange: str, length: int
    ) -> pd.DataFrame | None:
        """Return raw OHLCV rows for a pair."""
        symbol = self.utils.split_symbol(pair)
        start_date = self.__calculate_min_candle_date(timerange, length)
        return await self.__get_dataframe_for_symbol_since(symbol, start_date)

    async def get_data_for_pair_by_days(
        self, pair: str, lookback_days: int
    ) -> pd.DataFrame | None:
        """Return raw OHLCV rows for a pair using day-based lookback."""
        symbol = self.utils.split_symbol(pair)
        start_date = int(
            (
                datetime.now(timezone.utc) - timedelta(days=max(1, int(lookback_days)))
            ).timestamp()
            * 1000
        )
        return await self.__get_dataframe_for_symbol_since(symbol, start_date)

    def resample_data(self, ohlcv: pd.DataFrame, timerange: str) -> pd.DataFrame | None:
        """Resample OHLCV data to the requested timerange."""
        df = pd.DataFrame(ohlcv)
        if not df.empty:
            # Convert unix timestamp to datetime object
            df["timestamp"] = pd.to_datetime(
                df["timestamp"].astype(float), utc=True, origin="unix", unit="ms"
            )
            # Set datetime index
            df = df.set_index("timestamp")
            # Resample to the configured timerange
            if "m" in timerange:
                interval, range = timerange.split("m")
                timerange = f"{interval}Min"

            df_resample = df.resample(timerange).agg(
                {
                    "open": "first",
                    "high": "max",
                    "close": "last",
                    "low": "min",
                    "volume": "sum",
                }
            )

            # Reset index after resample
            df_resample.reset_index(inplace=True)

            # Convert datetime object back to a unix timestamp
            # df_resample["timestamp"] = df_resample["timestamp"].astype(int)
            # df_resample["timestamp"] = df_resample["timestamp"].div(10**9)

            # Clear empty values
            df_resample.dropna(inplace=True)
            return df_resample
        else:
            logging.error("No historic data available yet for symbol")

            return None
