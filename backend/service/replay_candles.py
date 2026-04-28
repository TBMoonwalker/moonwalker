"""Closed-trade replay candle archive helpers."""

from __future__ import annotations

from typing import Any

import ccxt.async_support as ccxt
import helper
import model
from service.config import Config, resolve_timeframe
from service.data_timeframes import timeframe_to_milliseconds
from service.exchange import Exchange
from service.sqlite_timestamps import (
    build_normalized_text_timestamp_sql,
    coerce_timestamp_like_to_ms,
)
from service.watcher_runtime import get_live_candle_snapshot
from tortoise import Tortoise

logging = helper.LoggerFactory.get_logger("logs/replay_candles.log", "replay_candles")

REPLAY_ARCHIVE_PRE_ROLL_MS = 2 * 24 * 60 * 60 * 1000
REPLAY_ARCHIVE_POST_ROLL_MS = 4 * 24 * 60 * 60 * 1000
NORMALIZED_TICKER_TIMESTAMP_SQL = build_normalized_text_timestamp_sql()


def _parse_optional_ms(value: Any) -> int | None:
    """Convert an arbitrary timestamp-like value into Unix milliseconds."""
    return coerce_timestamp_like_to_ms(value)


def _build_archive_row(
    *,
    timestamp: Any,
    open_price: Any,
    high_price: Any,
    low_price: Any,
    close_price: Any,
    volume: Any,
) -> dict[str, float | str] | None:
    """Normalize one candle-like payload into an archive-ready row."""
    timestamp_ms = _parse_optional_ms(timestamp)
    if timestamp_ms is None:
        return None

    try:
        return {
            "timestamp": str(timestamp_ms),
            "open": float(open_price),
            "high": float(high_price),
            "low": float(low_price),
            "close": float(close_price),
            "volume": float(volume),
        }
    except (TypeError, ValueError):
        return None


def _get_live_archive_row(
    symbol: str,
    *,
    start_ms: int,
    end_ms: int,
) -> dict[str, float | str] | None:
    """Return the current in-memory candle when it belongs in the archive."""
    snapshot = get_live_candle_snapshot(symbol)
    if not snapshot or len(snapshot) < 6:
        return None

    timestamp_ms = _parse_optional_ms(snapshot[0])
    if timestamp_ms is None or timestamp_ms < start_ms or timestamp_ms > end_ms:
        return None

    return _build_archive_row(
        timestamp=timestamp_ms,
        open_price=snapshot[1],
        high_price=snapshot[2],
        low_price=snapshot[3],
        close_price=snapshot[4],
        volume=snapshot[5],
    )


def _merge_archive_source_rows(
    ticker_rows: list[dict[str, Any]],
    live_row: dict[str, float | str] | None,
) -> list[dict[str, float | str]]:
    """Merge persisted ticker rows with the latest live candle snapshot."""
    rows_by_timestamp: dict[int, dict[str, float | str]] = {}

    for row in ticker_rows:
        normalized_row = _build_archive_row(
            timestamp=row.get("timestamp"),
            open_price=row.get("open"),
            high_price=row.get("high"),
            low_price=row.get("low"),
            close_price=row.get("close"),
            volume=row.get("volume"),
        )
        if normalized_row is None:
            continue
        timestamp_ms = _parse_optional_ms(normalized_row["timestamp"])
        if timestamp_ms is None:
            continue
        rows_by_timestamp[timestamp_ms] = normalized_row

    if live_row is not None:
        live_timestamp_ms = _parse_optional_ms(live_row["timestamp"])
        if live_timestamp_ms is not None:
            rows_by_timestamp[live_timestamp_ms] = live_row

    return [rows_by_timestamp[timestamp] for timestamp in sorted(rows_by_timestamp)]


def _extract_archive_timestamps_ms(
    rows: list[dict[str, float | str]] | list[dict[str, Any]],
) -> set[int]:
    """Return normalized archive-row timestamps as Unix milliseconds."""
    timestamps: set[int] = set()
    for row in rows:
        timestamp_ms = _parse_optional_ms(row.get("timestamp"))
        if timestamp_ms is not None:
            timestamps.add(timestamp_ms)
    return timestamps


def _score_archive_timestamps(
    timestamps: set[int],
    *,
    start_ms: int,
    end_ms: int,
    timeframe_ms: int,
) -> tuple[int, int, int]:
    """Score archive coverage by completeness, density, and recency."""
    if not timestamps:
        return (0, 0, -1)

    normalized_start = max(
        0, ((start_ms + timeframe_ms - 1) // timeframe_ms) * timeframe_ms
    )
    normalized_end = (end_ms // timeframe_ms) * timeframe_ms
    if normalized_end < normalized_start:
        return (0, len(timestamps), max(timestamps))

    expected_timestamps = set(
        range(normalized_start, normalized_end + timeframe_ms, timeframe_ms)
    )
    is_complete = int(expected_timestamps.issubset(timestamps))
    return (is_complete, len(timestamps), max(timestamps))


async def _get_archived_timestamps_ms(
    deal_id: str,
    *,
    conn: Any | None = None,
) -> set[int]:
    """Return archived replay-candle timestamps for one deal."""
    query = model.TradeReplayCandles.filter(deal_id=deal_id)
    if conn is not None:
        query = query.using_db(conn)
    rows = await query.values("timestamp")
    return _extract_archive_timestamps_ms(rows)


async def resolve_replay_archive_window_ms(
    deal_id: str,
    *,
    open_date: Any,
    close_date: Any,
    conn: Any | None = None,
) -> tuple[int | None, int | None]:
    """Resolve the archived replay window for one deal in milliseconds."""
    query = model.TradeExecutions.filter(deal_id=deal_id)
    if conn is not None:
        query = query.using_db(conn)
    executions = await query.values("side", "timestamp")

    buy_timestamps = sorted(
        timestamp
        for timestamp in (
            _parse_optional_ms(execution.get("timestamp"))
            for execution in executions
            if str(execution.get("side") or "") == "buy"
        )
        if timestamp is not None
    )
    sell_timestamps = sorted(
        timestamp
        for timestamp in (
            _parse_optional_ms(execution.get("timestamp"))
            for execution in executions
            if str(execution.get("side") or "") == "sell"
        )
        if timestamp is not None
    )

    start_ms = buy_timestamps[0] if buy_timestamps else _parse_optional_ms(open_date)
    end_ms = sell_timestamps[-1] if sell_timestamps else _parse_optional_ms(close_date)
    if start_ms is None or end_ms is None or end_ms < start_ms:
        return None, None

    return (
        max(0, start_ms - REPLAY_ARCHIVE_PRE_ROLL_MS),
        end_ms + REPLAY_ARCHIVE_POST_ROLL_MS,
    )


async def _fetch_exchange_archive_rows(
    symbol: str,
    *,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, float | str]]:
    """Fetch replay-archive candles directly from the exchange for repair."""
    config = await Config.instance()
    snapshot = config.snapshot()
    exchange_name = str(snapshot.get("exchange") or "").strip()
    if not exchange_name:
        return []

    timeframe = resolve_timeframe(snapshot)
    exchange = Exchange()
    try:
        candles = await exchange.get_history_for_symbol(
            snapshot,
            symbol,
            timeframe,
            limit=1000,
            since=start_ms,
            until=end_ms,
        )
    except (
        ccxt.BaseError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        logging.warning(
            "Replay archive exchange repair failed for %s (%s-%s): %s",
            symbol,
            start_ms,
            end_ms,
            exc,
        )
        return []
    finally:
        await exchange.close()

    exchange_rows: list[dict[str, float | str]] = []
    for candle in candles:
        if not isinstance(candle, (list, tuple)) or len(candle) < 6:
            continue
        timestamp_ms = _parse_optional_ms(candle[0])
        if timestamp_ms is None or timestamp_ms < start_ms or timestamp_ms > end_ms:
            continue
        archive_row = _build_archive_row(
            timestamp=timestamp_ms,
            open_price=candle[1],
            high_price=candle[2],
            low_price=candle[3],
            close_price=candle[4],
            volume=candle[5],
        )
        if archive_row is not None:
            exchange_rows.append(archive_row)

    return _merge_archive_source_rows(exchange_rows, None)


async def archive_replay_candles_for_deal(
    deal_id: str,
    symbol: str,
    *,
    open_date: Any,
    close_date: Any,
    conn: Any | None = None,
    allow_missing_archive_exchange_repair: bool = False,
) -> int:
    """Copy the bounded replay candle window into the per-deal archive table."""
    normalized_deal_id = str(deal_id or "").strip()
    normalized_symbol = str(symbol or "").strip()
    if not normalized_deal_id or not normalized_symbol:
        return 0

    start_ms, end_ms = await resolve_replay_archive_window_ms(
        normalized_deal_id,
        open_date=open_date,
        close_date=close_date,
        conn=conn,
    )
    if start_ms is None or end_ms is None:
        return 0

    connection = conn or Tortoise.get_connection("default")
    live_row = _get_live_archive_row(
        normalized_symbol,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    archived_timestamps = await _get_archived_timestamps_ms(
        normalized_deal_id,
        conn=conn,
    )

    ticker_rows = await connection.execute_query_dict(
        "SELECT timestamp, open, high, low, close, volume "
        "FROM tickers "
        "WHERE symbol = ? "
        f"AND {NORMALIZED_TICKER_TIMESTAMP_SQL} >= ? "
        f"AND {NORMALIZED_TICKER_TIMESTAMP_SQL} <= ? "
        f"ORDER BY {NORMALIZED_TICKER_TIMESTAMP_SQL}, timestamp",
        [normalized_symbol, start_ms, end_ms],
    )
    source_rows = _merge_archive_source_rows(
        ticker_rows,
        live_row,
    )
    timeframe_ms = max(
        1,
        timeframe_to_milliseconds(
            resolve_timeframe((await Config.instance()).snapshot())
        ),
    )
    source_timestamps = _extract_archive_timestamps_ms(source_rows)
    best_source_rows = source_rows
    best_score = _score_archive_timestamps(
        source_timestamps,
        start_ms=start_ms,
        end_ms=end_ms,
        timeframe_ms=timeframe_ms,
    )
    archived_score = _score_archive_timestamps(
        archived_timestamps,
        start_ms=start_ms,
        end_ms=end_ms,
        timeframe_ms=timeframe_ms,
    )

    should_try_exchange_repair = live_row is None and (
        (bool(archived_timestamps) and archived_score[0] == 0)
        or (
            allow_missing_archive_exchange_repair
            and not archived_timestamps
            and len(source_rows) <= 2
        )
    )
    if should_try_exchange_repair:
        exchange_rows = await _fetch_exchange_archive_rows(
            normalized_symbol,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        exchange_timestamps = _extract_archive_timestamps_ms(exchange_rows)
        exchange_score = _score_archive_timestamps(
            exchange_timestamps,
            start_ms=start_ms,
            end_ms=end_ms,
            timeframe_ms=timeframe_ms,
        )
        if exchange_score > best_score:
            best_source_rows = exchange_rows
            best_score = exchange_score
            source_timestamps = exchange_timestamps

    if not best_source_rows:
        return 0

    if live_row is None and archived_timestamps:
        if best_score <= archived_score:
            return 0
        if source_timestamps == archived_timestamps:
            return 0

    if archived_timestamps:
        if conn is not None:
            await model.TradeReplayCandles.filter(deal_id=normalized_deal_id).using_db(
                conn
            ).delete()
        else:
            await model.TradeReplayCandles.filter(deal_id=normalized_deal_id).delete()

    archive_rows = [
        model.TradeReplayCandles(
            deal_id=normalized_deal_id,
            symbol=normalized_symbol,
            timestamp=str(row["timestamp"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for row in best_source_rows
    ]
    if conn is not None:
        await model.TradeReplayCandles.bulk_create(archive_rows, using_db=conn)
    else:
        await model.TradeReplayCandles.bulk_create(archive_rows)
    return len(archive_rows)
