"""Shared completed OHLCV windows and planning helpers for history backfill."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from weakref import WeakKeyDictionary

from cachetools import TTLCache


@dataclass(frozen=True)
class HistorySyncWindow:
    """Normalized required OHLCV window for one history sync request."""

    required_since: int
    required_until: int
    timeframe_ms: int
    required_timestamps: set[int]

    @classmethod
    def build(
        cls,
        *,
        required_since: int,
        required_until: int,
        timeframe_ms: int,
    ) -> "HistorySyncWindow":
        """Build a normalized history sync window."""
        return cls(
            required_since=required_since,
            required_until=required_until,
            timeframe_ms=timeframe_ms,
            required_timestamps=build_required_timestamps(
                required_since=required_since,
                required_until=required_until,
                timeframe_ms=timeframe_ms,
            ),
        )


@dataclass
class HistorySyncState:
    """Mutable progress for one history sync attempt."""

    stored_timestamps: set[int]
    earliest_available_timestamp: int | None = None

    def is_required_complete(self, window: HistorySyncWindow) -> bool:
        """Return True when all required candle timestamps are present."""
        return window.required_timestamps.issubset(self.stored_timestamps)

    def is_complete_from_first_available(self, window: HistorySyncWindow) -> bool:
        """Return True when history is complete from the first exchange candle onward."""
        return is_complete_since_first_available_candle(
            stored_timestamps=self.stored_timestamps,
            available_since=self.earliest_available_timestamp,
            required_until=window.required_until,
            timeframe_ms=window.timeframe_ms,
        )

    def record_fetch(
        self,
        *,
        fetched_timestamps: set[int],
        inserted_timestamps: set[int],
    ) -> None:
        """Record one fetch attempt into the current history sync state."""
        if fetched_timestamps:
            fetched_earliest = min(fetched_timestamps)
            if self.earliest_available_timestamp is None:
                self.earliest_available_timestamp = fetched_earliest
            else:
                self.earliest_available_timestamp = min(
                    self.earliest_available_timestamp,
                    fetched_earliest,
                )

        self.stored_timestamps.update(inserted_timestamps)

    def missing_count(self, window: HistorySyncWindow) -> int:
        """Return the remaining number of missing required timestamps."""
        return len(window.required_timestamps - self.stored_timestamps)


def build_required_timestamps(
    required_since: int,
    required_until: int,
    timeframe_ms: int,
) -> set[int]:
    """Build the exact timestamp set required for a history window."""
    if timeframe_ms <= 0 or required_until < required_since:
        return set()
    return set(range(required_since, required_until + 1, timeframe_ms))


def is_complete_since_first_available_candle(
    *,
    stored_timestamps: set[int],
    available_since: int | None,
    required_until: int,
    timeframe_ms: int,
) -> bool:
    """Return True when history is complete from the first exchange candle onward."""
    if available_since is None or timeframe_ms <= 0 or required_until < available_since:
        return False

    effective_required = build_required_timestamps(
        required_since=available_since,
        required_until=required_until,
        timeframe_ms=timeframe_ms,
    )
    return bool(effective_required) and effective_required.issubset(stored_timestamps)


def plan_boundary_fetch_starts(
    *,
    window: HistorySyncWindow,
    stored_timestamps: set[int],
) -> list[int]:
    """Plan fetch start timestamps for missing boundary segments."""
    if not stored_timestamps:
        return [window.required_since]

    fetch_starts: list[int] = []
    earliest_stored = min(stored_timestamps)
    latest_stored = max(stored_timestamps)

    if earliest_stored > window.required_since:
        fetch_starts.append(window.required_since)
    if latest_stored < window.required_until:
        fetch_starts.append(latest_stored + window.timeframe_ms)

    if not fetch_starts:
        return [window.required_since]

    return list(dict.fromkeys(fetch_starts))


class CompletedHistoryWindows:
    """Coalesce source-qualified windows without sharing authenticated clients.

    Only complete windows are cached. A cancelled fetch owns no detached task;
    the next waiter retries through its own client's existing lifecycle.
    """

    def __init__(self) -> None:
        self._rows: TTLCache[str, tuple[tuple[Any, ...], ...]] = TTLCache(
            maxsize=20000, ttl=60, getsizeof=len
        )
        self._locks: dict[str, tuple[asyncio.Lock, int]] = {}

    async def read(
        self,
        *,
        config: dict[str, Any],
        symbol: str,
        timeframe: str,
        window: HistorySyncWindow,
        fetch: Callable[[], Awaitable[list[list[Any]]]],
    ) -> list[list[Any]]:
        """Return defensive rows for one exact completed window.

        All configuration participates in invalidation, including venue, market,
        sandbox and credential changes. The digest never exposes credentials.
        Legacy unqualified ticker rows are deliberately not a cache input.
        """
        if not window.required_timestamps or len(window.required_timestamps) > 20000:
            return await fetch()
        key = hashlib.sha256(
            json.dumps(
                [
                    config,
                    symbol,
                    timeframe,
                    window.required_since,
                    window.required_until,
                    window.timeframe_ms,
                ],
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        lock, users = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = (lock, users + 1)
        try:
            async with lock:
                cached = self._rows.get(key)
                if cached is not None:
                    return [list(row) for row in cached]
                rows = [
                    row
                    for row in await fetch()
                    if not (
                        isinstance(row, (list, tuple))
                        and row
                        and isinstance(row[0], (int, float))
                        and not window.required_since <= row[0] <= window.required_until
                    )
                ]
                # Do not normalize malformed evidence into valid market data.
                valid = all(
                    isinstance(row, (list, tuple))
                    and len(row) >= 6
                    and isinstance(row[0], (int, float))
                    and row[0] in window.required_timestamps
                    for row in rows
                )
                timestamps = {row[0] for row in rows} if valid else set()
                if (
                    valid
                    and timestamps == window.required_timestamps
                    and len(rows) == len(timestamps)
                ):
                    self._rows[key] = tuple(tuple(row) for row in rows)
                return [
                    list(row) if isinstance(row, (list, tuple)) else row for row in rows
                ]
        finally:
            _, users = self._locks[key]
            if users == 1:
                del self._locks[key]
            else:
                self._locks[key] = (lock, users - 1)


_completed_windows: WeakKeyDictionary[
    asyncio.AbstractEventLoop, CompletedHistoryWindows
] = WeakKeyDictionary()


async def completed_history_window(
    *,
    config: dict[str, Any],
    symbol: str,
    timeframe: str,
    window: HistorySyncWindow,
    fetch: Callable[[], Awaitable[list[list[Any]]]],
) -> list[list[Any]]:
    """Share bounded history windows within the current application event loop."""
    loop = asyncio.get_running_loop()
    windows = _completed_windows.get(loop)
    if windows is None:
        windows = CompletedHistoryWindows()
        _completed_windows[loop] = windows
    return await windows.read(
        config=config, symbol=symbol, timeframe=timeframe, window=window, fetch=fetch
    )
