from datetime import datetime, timezone

from service.data_timeframes import (
    calculate_min_candle_date,
    resolve_required_history_window,
    timeframe_to_milliseconds,
    timeframe_to_seconds,
)


def test_timeframe_to_seconds_supports_min_alias_and_invalid_fallback() -> None:
    assert timeframe_to_seconds("15min") == 900
    assert timeframe_to_seconds("4h") == 14_400
    assert timeframe_to_seconds("invalid") == 60


def test_timeframe_to_milliseconds_scales_seconds() -> None:
    assert timeframe_to_milliseconds("1m") == 60_000
    assert timeframe_to_milliseconds("1d") == 86_400_000


def test_calculate_min_candle_date_applies_lookback_buffer() -> None:
    now = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    result = calculate_min_candle_date(
        timerange="1h",
        length=2,
        lookback_buffer_multiplier=2,
        now=now,
    )

    assert result == int(
        datetime(2023, 12, 31, 20, 0, tzinfo=timezone.utc).timestamp() * 1000
    )


def test_resolve_required_history_window_aligns_to_closed_candle_boundaries() -> None:
    now = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)

    required_since, required_until, timeframe_ms = resolve_required_history_window(
        history_data=30,
        timeframe="1h",
        since_ms=int(
            datetime(2024, 1, 1, 8, 30, tzinfo=timezone.utc).timestamp() * 1000
        ),
        now=now,
    )

    assert timeframe_ms == 3_600_000
    assert required_since == int(
        datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc).timestamp() * 1000
    )
    assert required_until == int(
        datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc).timestamp() * 1000
    )
