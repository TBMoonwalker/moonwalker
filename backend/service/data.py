"""Data access helpers for OHLCV and listings."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import ccxt.async_support as ccxt
import helper
import model
import pandas as pd
from cachetools import TTLCache
from service.config import resolve_timeframe
from service.data_history_sync import (
    HistorySyncState,
    HistorySyncWindow,
    plan_boundary_fetch_starts,
)
from service.data_ohlcv import (
    build_archived_ohlcv_payload,
    build_live_candle_payload,
    build_pair_ohlcv_payload,
    resample_ohlcv_data,
    rows_to_dataframe,
)
from service.data_timeframes import (
    calculate_min_candle_date,
    resolve_required_history_window,
    timeframe_to_milliseconds,
)
from service.database import run_sqlite_write_with_retry
from service.exchange import Exchange
from service.replay_candles import archive_replay_candles_for_deal
from service.sqlite_timestamps import build_normalized_text_timestamp_sql
from service.watcher_runtime import get_live_candle_snapshot
from tortoise import Tortoise
from tortoise.exceptions import BaseORMException

logging = helper.LoggerFactory.get_logger("logs/data.log", "data")

_TIME_SERIES_QUERY_SPECS: dict[str, tuple[str, tuple[str, ...]]] = {
    "tickers": (
        "symbol",
        ("id", "timestamp", "symbol", "open", "high", "low", "close", "volume"),
    ),
    "tradereplaycandles": (
        "deal_id",
        (
            "id",
            "deal_id",
            "symbol",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ),
    ),
}
_NORMALIZED_ROW_TIMESTAMP_SQL = build_normalized_text_timestamp_sql()


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
        rows = await Tortoise.get_connection("default").execute_query_dict(
            "SELECT timestamp FROM tickers "
            "WHERE symbol = ? "
            f"ORDER BY {_NORMALIZED_ROW_TIMESTAMP_SQL} DESC, timestamp DESC "
            "LIMIT 1",
            [symbol],
        )
        if not rows:
            return None
        return float(rows[0]["timestamp"])

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

    async def __get_stored_timestamps(
        self, symbol: str, since_ms: int, until_ms: int
    ) -> set[int]:
        """Return stored timestamps for a symbol within the required window."""
        rows = await self.__query_rows_with_numeric_timestamp(
            table_name="tickers",
            identity_value=symbol,
            start_timestamp=since_ms,
            end_timestamp=until_ms,
            fields=("timestamp",),
            start_operator=">=",
        )
        timestamps: set[int] = set()
        for row in rows:
            try:
                timestamps.add(int(float(row["timestamp"])))
            except (TypeError, ValueError):
                continue
        return timestamps

    async def __query_rows_with_numeric_timestamp(
        self,
        *,
        table_name: str,
        identity_value: str,
        start_timestamp: int | float | None = None,
        end_timestamp: int | float | None = None,
        fields: tuple[str, ...] | None = None,
        start_operator: str = ">=",
    ) -> list[dict[str, Any]]:
        """Query rows using numeric timestamp ordering against text-backed columns."""
        if start_operator not in {">", ">="}:
            raise ValueError(f"Unsupported start operator: {start_operator}")

        identity_column, allowed_fields = _TIME_SERIES_QUERY_SPECS[table_name]
        selected_fields = fields or allowed_fields
        invalid_fields = [
            field for field in selected_fields if field not in allowed_fields
        ]
        if invalid_fields:
            raise ValueError(
                f"Unsupported fields for {table_name}: {', '.join(invalid_fields)}"
            )

        where_clauses = [f"{identity_column} = ?"]
        params: list[Any] = [identity_value]
        if start_timestamp is not None:
            where_clauses.append(f"{_NORMALIZED_ROW_TIMESTAMP_SQL} {start_operator} ?")
            params.append(int(float(start_timestamp)))
        if end_timestamp is not None:
            where_clauses.append(f"{_NORMALIZED_ROW_TIMESTAMP_SQL} <= ?")
            params.append(int(float(end_timestamp)))

        query = (
            f"SELECT {', '.join(selected_fields)} "
            f"FROM {table_name} "
            f"WHERE {' AND '.join(where_clauses)} "
            f"ORDER BY {_NORMALIZED_ROW_TIMESTAMP_SQL}, timestamp"
        )
        return await Tortoise.get_connection("default").execute_query_dict(
            query, params
        )

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

    async def count_history_data_for_symbol(self, symbol: str) -> int | bool:
        """Count history data rows for a symbol."""
        try:
            query = await model.Tickers.filter(symbol=f"{symbol}").count()
            logging.debug("Counted %s entries for symbol %s", query, symbol)
            return query
        except BaseORMException as e:
            logging.error("Error counting history data for symbol %s: %s", symbol, e)

        return False

    async def get_resampled_history_candle_count(
        self, symbol: str, timerange: str, minimum_candles: int
    ) -> int:
        """Return the number of stored closed candles available after resampling."""
        if minimum_candles <= 0:
            return 0

        try:
            df_raw = await self.get_data_for_pair(symbol, timerange, minimum_candles)
            if df_raw is None or df_raw.empty:
                return 0

            df = await asyncio.to_thread(self.resample_data, df_raw, timerange)
            if df is None or df.empty:
                return 0

            return int(len(df.index))
        except (
            BaseORMException,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            logging.error(
                "Error counting resampled history candles for %s (%s): %s",
                symbol,
                timerange,
                e,
            )
            return 0

    async def has_sufficient_resampled_history(
        self, symbol: str, timerange: str, minimum_candles: int
    ) -> bool:
        """Return True when enough closed candles exist for the requested timeframe."""
        if minimum_candles <= 0:
            return True

        available_candles = await self.get_resampled_history_candle_count(
            symbol,
            timerange,
            minimum_candles,
        )
        return available_candles >= int(minimum_candles)

    async def add_history_data_for_symbol(
        self,
        symbol: str,
        history_data: int,
        config: dict[str, Any],
        since_ms: int | None = None,
    ) -> bool:
        """Ensure required history exists for a symbol without deleting stored data."""
        try:
            required_since, required_until, timeframe_ms = (
                resolve_required_history_window(
                    history_data=history_data,
                    timeframe=resolve_timeframe(config),
                    since_ms=since_ms,
                )
            )
            window = HistorySyncWindow.build(
                required_since=required_since,
                required_until=required_until,
                timeframe_ms=timeframe_ms,
            )
            if not window.required_timestamps:
                logging.warning("No closed candle window available yet for %s.", symbol)
                return False

            sync_state = HistorySyncState(
                stored_timestamps=await self.__get_stored_timestamps(
                    symbol,
                    window.required_since,
                    window.required_until,
                )
            )
            if sync_state.is_required_complete(window):
                logging.info("History already complete for %s", symbol)
                return True

            for fetch_since in plan_boundary_fetch_starts(
                window=window,
                stored_timestamps=sync_state.stored_timestamps,
            ):
                fetched_timestamps, inserted_timestamps = (
                    await self.__fetch_and_store_history_range(
                        symbol=symbol,
                        config=config,
                        fetch_since_ms=fetch_since,
                        required_since=window.required_since,
                        required_until=window.required_until,
                        required_timestamps=window.required_timestamps,
                        existing_timestamps=sync_state.stored_timestamps,
                    )
                )
                sync_state.record_fetch(
                    fetched_timestamps=fetched_timestamps,
                    inserted_timestamps=inserted_timestamps,
                )

            if sync_state.is_required_complete(window):
                logging.info("Added missing history boundaries for %s", symbol)
                return True

            if sync_state.is_complete_from_first_available(window):
                logging.info(
                    "Added history for %s from first available exchange candle at %s",
                    symbol,
                    sync_state.earliest_available_timestamp,
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
                    fetch_since_ms=window.required_since,
                    required_since=window.required_since,
                    required_until=window.required_until,
                    required_timestamps=window.required_timestamps,
                    existing_timestamps=sync_state.stored_timestamps,
                )
            )
            sync_state.record_fetch(
                fetched_timestamps=refill_fetched_timestamps,
                inserted_timestamps=refill_inserted_timestamps,
            )

            if sync_state.is_required_complete(window):
                logging.info("Added history for %s", symbol)
                return True

            if sync_state.is_complete_from_first_available(window):
                logging.info(
                    "Added history for %s from first available exchange candle at %s",
                    symbol,
                    sync_state.earliest_available_timestamp,
                )
                return True

            missing_count = sync_state.missing_count(window)
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
        end_timestamp: int | float | None = None,
        fields: tuple[str, ...] | None = None,
    ) -> pd.DataFrame | None:
        """Return ticker rows for a symbol since a timestamp as a DataFrame."""
        rows = await self.__query_rows_with_numeric_timestamp(
            table_name="tickers",
            identity_value=symbol,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            fields=fields,
            start_operator=">",
        )
        if not rows:
            return None
        return await asyncio.to_thread(rows_to_dataframe, rows)

    async def __get_dataframe_for_replay_deal(
        self,
        deal_id: str,
        start_timestamp: int | float | None = None,
        end_timestamp: int | float | None = None,
        fields: tuple[str, ...] | None = None,
    ) -> pd.DataFrame | None:
        """Return archived replay candles for a deal as a DataFrame."""
        rows = await self.__query_rows_with_numeric_timestamp(
            table_name="tradereplaycandles",
            identity_value=deal_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            fields=fields,
            start_operator=">=",
        )
        if not rows:
            return None
        return await asyncio.to_thread(rows_to_dataframe, rows)

    async def __repair_archived_replay_if_needed(
        self,
        deal_id: str,
        timerange: str,
        timestamp_start: float | None,
        timestamp_end: float | None,
        df_source: pd.DataFrame | None,
    ) -> pd.DataFrame | None:
        """Repair a legacy replay archive on demand when a chart would be sparse."""
        current_row_count = 0 if df_source is None else len(df_source.index)
        if df_source is not None and not df_source.empty and current_row_count > 2:
            return df_source

        should_repair_missing_archive = df_source is None or df_source.empty
        if not should_repair_missing_archive and timestamp_end is not None:
            requested_window_ms = max(0, int(timestamp_end) - int(timestamp_start or 0))
            should_repair_missing_archive = requested_window_ms > (
                timeframe_to_milliseconds(timerange) * 2
            )

        if not should_repair_missing_archive:
            return df_source

        closed_trade = await model.ClosedTrades.get_or_none(deal_id=deal_id)
        if (
            closed_trade is None
            or not str(closed_trade.symbol or "").strip()
            or closed_trade.open_date is None
            or closed_trade.close_date is None
        ):
            return df_source

        archived_rows = await archive_replay_candles_for_deal(
            deal_id,
            closed_trade.symbol,
            open_date=closed_trade.open_date,
            close_date=closed_trade.close_date,
            allow_missing_archive_exchange_repair=True,
        )
        if archived_rows <= 0:
            return df_source

        repaired_df = await self.__get_dataframe_for_replay_deal(
            deal_id,
            start_timestamp=timestamp_start,
            end_timestamp=timestamp_end,
            fields=("timestamp", "open", "high", "low", "close", "volume"),
        )
        if repaired_df is None:
            return df_source
        if current_row_count >= len(repaired_df.index):
            return df_source
        return repaired_df

    async def get_ohlcv_for_pair(
        self,
        pair: str,
        timerange: str,
        timestamp_start: float,
        offset: float,
        timestamp_end: float | None = None,
    ) -> str | dict[str, Any]:
        """Return OHLCV data for a pair and timerange."""
        symbol = self.utils.split_symbol(pair)
        start_timestamp = float(timestamp_start) - 60000
        df_source = await self.__get_dataframe_for_symbol_since(
            symbol,
            start_timestamp,
            end_timestamp=timestamp_end,
            fields=("timestamp", "open", "high", "low", "close", "volume"),
        )
        if df_source is None:
            df_source = pd.DataFrame()
        live_candle = self.__get_live_candle_for_symbol(
            symbol,
            start_timestamp,
            end_timestamp=timestamp_end,
        )
        return await asyncio.to_thread(
            build_pair_ohlcv_payload,
            df_source,
            timerange,
            offset,
            live_candle=live_candle,
        )

    async def get_archived_ohlcv_for_deal(
        self,
        deal_id: str,
        timerange: str,
        timestamp_start: float | None,
        timestamp_end: float | None,
        offset: float,
    ) -> str | dict[str, Any]:
        """Return archived replay OHLCV data for one closed deal."""
        try:
            normalized_deal_id = str(UUID(str(deal_id)))
        except (TypeError, ValueError):
            return {}

        df_source = await self.__get_dataframe_for_replay_deal(
            normalized_deal_id,
            start_timestamp=timestamp_start,
            end_timestamp=timestamp_end,
            fields=("timestamp", "open", "high", "low", "close", "volume"),
        )
        df_source = await self.__repair_archived_replay_if_needed(
            normalized_deal_id,
            timerange,
            timestamp_start,
            timestamp_end,
            df_source,
        )
        return await asyncio.to_thread(
            build_archived_ohlcv_payload,
            df_source,
            timerange,
            offset,
        )

    def __get_live_candle_for_symbol(
        self,
        symbol: str,
        start_timestamp: float,
        end_timestamp: float | None = None,
    ) -> dict[str, float | str] | None:
        """Return current in-memory watcher candle for symbol if it is in range."""
        if end_timestamp is not None:
            return None
        try:
            live = get_live_candle_snapshot(symbol)
            return build_live_candle_payload(live, symbol, start_timestamp)
        except (
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
        start_date = calculate_min_candle_date(
            timerange=timerange,
            length=length,
            lookback_buffer_multiplier=self.LOOKBACK_BUFFER_MULTIPLIER,
        )
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
        df_resample = resample_ohlcv_data(ohlcv, timerange)
        if df_resample is None:
            logging.error("No historic data available yet for symbol")
            return None
        return df_resample
