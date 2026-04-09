"""Closed-trade replay candle archive helpers."""

from __future__ import annotations

from typing import Any

import model
from service.sqlite_timestamps import (
    build_normalized_text_timestamp_sql,
    coerce_timestamp_like_to_ms,
)
from service.watcher_runtime import get_live_candle_snapshot
from tortoise import Tortoise

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


async def _get_latest_archived_timestamp_ms(
    deal_id: str,
    *,
    conn: Any | None = None,
) -> int | None:
    """Return the latest archived replay-candle timestamp for one deal."""
    query = model.TradeReplayCandles.filter(deal_id=deal_id)
    if conn is not None:
        query = query.using_db(conn)
    rows = await query.values("timestamp")
    timestamps = [
        timestamp_ms
        for timestamp_ms in (_parse_optional_ms(row.get("timestamp")) for row in rows)
        if timestamp_ms is not None
    ]
    return max(timestamps) if timestamps else None


async def _get_latest_persisted_ticker_timestamp_ms(
    symbol: str,
    *,
    start_ms: int,
    end_ms: int,
    connection: Any,
) -> int | None:
    """Return the latest persisted ticker timestamp inside the archive window."""
    rows = await connection.execute_query_dict(
        "SELECT MAX("
        f"{NORMALIZED_TICKER_TIMESTAMP_SQL}"
        ") AS timestamp_ms "
        "FROM tickers "
        "WHERE symbol = ? "
        f"AND {NORMALIZED_TICKER_TIMESTAMP_SQL} >= ? "
        f"AND {NORMALIZED_TICKER_TIMESTAMP_SQL} <= ?",
        [symbol, start_ms, end_ms],
    )
    if not rows:
        return None
    return _parse_optional_ms(rows[0].get("timestamp_ms"))


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


async def archive_replay_candles_for_deal(
    deal_id: str,
    symbol: str,
    *,
    open_date: Any,
    close_date: Any,
    conn: Any | None = None,
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
    latest_archived_ms = await _get_latest_archived_timestamp_ms(
        normalized_deal_id,
        conn=conn,
    )
    latest_persisted_ms = await _get_latest_persisted_ticker_timestamp_ms(
        normalized_symbol,
        start_ms=start_ms,
        end_ms=end_ms,
        connection=connection,
    )
    latest_live_ms = (
        _parse_optional_ms(live_row["timestamp"]) if live_row is not None else None
    )
    latest_source_ms = (
        max(
            timestamp_ms
            for timestamp_ms in (latest_persisted_ms, latest_live_ms)
            if timestamp_ms is not None
        )
        if latest_persisted_ms is not None or latest_live_ms is not None
        else None
    )
    if (
        latest_archived_ms is not None
        and latest_source_ms is not None
        and latest_archived_ms >= latest_source_ms
    ):
        return 0

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
    if not source_rows:
        return 0

    if latest_archived_ms is not None:
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
        for row in source_rows
    ]
    if conn is not None:
        await model.TradeReplayCandles.bulk_create(archive_rows, using_db=conn)
    else:
        await model.TradeReplayCandles.bulk_create(archive_rows)
    return len(archive_rows)
