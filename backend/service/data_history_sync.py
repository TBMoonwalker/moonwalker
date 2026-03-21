"""Pure planning helpers for OHLCV history backfill."""

from __future__ import annotations

from dataclasses import dataclass


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
