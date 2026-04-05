"""Closed-trade replay candle archive helpers."""

from __future__ import annotations

from typing import Any

import model
from service.trade_math import parse_date_to_ms

REPLAY_ARCHIVE_PRE_ROLL_MS = 2 * 24 * 60 * 60 * 1000
REPLAY_ARCHIVE_POST_ROLL_MS = 4 * 24 * 60 * 60 * 1000


def _parse_optional_ms(value: Any) -> int | None:
    """Convert an arbitrary timestamp-like value into Unix milliseconds."""
    if value is None:
        return None
    return parse_date_to_ms(str(value))


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

    archive_query = model.TradeReplayCandles.filter(deal_id=normalized_deal_id)
    if conn is not None:
        archive_query = archive_query.using_db(conn)
    if await archive_query.exists():
        return 0

    start_ms, end_ms = await resolve_replay_archive_window_ms(
        normalized_deal_id,
        open_date=open_date,
        close_date=close_date,
        conn=conn,
    )
    if start_ms is None or end_ms is None:
        return 0

    ticker_query = model.Tickers.filter(
        symbol=normalized_symbol,
        timestamp__gte=start_ms,
        timestamp__lte=end_ms,
    ).order_by("timestamp")
    if conn is not None:
        ticker_query = ticker_query.using_db(conn)
    ticker_rows = await ticker_query.values(
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    )
    if not ticker_rows:
        return 0

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
        for row in ticker_rows
    ]
    if conn is not None:
        await model.TradeReplayCandles.bulk_create(archive_rows, using_db=conn)
    else:
        await model.TradeReplayCandles.bulk_create(archive_rows)
    return len(archive_rows)
