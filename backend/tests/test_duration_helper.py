"""Tests for extracted duration parser helpers (regression for T1)."""

from datetime import UTC, datetime

import pytest
from helper import datetimes


class TestParseDurationHours:
    """Verify _parse_duration_hours behaviour after extraction."""

    def test_none_returns_none(self) -> None:
        assert datetimes.parse_duration_hours(None) is None

    def test_numeric_seconds(self) -> None:
        assert datetimes.parse_duration_hours(7200) == 2.0

    def test_numeric_hours(self) -> None:
        assert datetimes.parse_duration_hours(3600) == 1.0

    def test_numeric_minutes(self) -> None:
        assert datetimes.parse_duration_hours(90) == 1.5

    def test_numeric_sub_minute(self) -> None:
        assert datetimes.parse_duration_hours(45) == 45

    def test_timedelta_string_basic(self) -> None:
        result = datetimes.parse_duration_hours("3:45:00")
        assert result == pytest.approx(3.75)

    def test_timedelta_string_with_days(self) -> None:
        result = datetimes.parse_duration_hours("2 days, 3:45:30")
        expected = 2 * 24 + 3 + 45 / 60 + 30 / 3600
        assert result == pytest.approx(expected)

    def test_timedelta_string_with_microseconds(self) -> None:
        result = datetimes.parse_duration_hours("0:10:00.500000")
        assert result == pytest.approx(10 / 60 + 0.5 / 3600)

    def test_string_numeric_seconds(self) -> None:
        assert datetimes.parse_duration_hours("7200") == 2.0

    def test_string_numeric_hours(self) -> None:
        assert datetimes.parse_duration_hours("3600") == 1.0

    def test_empty_string_returns_none(self) -> None:
        assert datetimes.parse_duration_hours("") is None

    def test_garbage_string_returns_none(self) -> None:
        assert datetimes.parse_duration_hours("not-a-duration") is None

    def test_open_close_dates_override(self) -> None:
        opened = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        closed = datetime(2026, 1, 1, 13, 30, 0, tzinfo=UTC)
        result = datetimes.parse_duration_hours(
            "0:00:00", open_date=opened, close_date=closed
        )
        assert result == pytest.approx(3.5)

    def test_open_close_dates_inverted_returns_zero(self) -> None:
        closed = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        opened = datetime(2026, 1, 1, 13, 0, 0, tzinfo=UTC)
        result = datetimes.parse_duration_hours(
            "0:00:00", open_date=opened, close_date=closed
        )
        assert result == 0.0

    def test_open_close_dates_missing_falls_back(self) -> None:
        result = datetimes.parse_duration_hours(
            "7200", open_date=None, close_date="invalid"
        )
        assert result == pytest.approx(2.0)

    def test_parse_isoformat_date(self) -> None:
        dt = datetimes.parse_datetime("2026-03-15T10:00:00+00:00")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 3

    def test_parse_unix_timestamp_seconds(self) -> None:
        ts = 1_711_440_000
        dt = datetimes.parse_datetime(ts)
        assert dt is not None

    def test_parse_unix_timestamp_millis(self) -> None:
        ts = 1_711_440_000_000
        dt = datetimes.parse_datetime(ts)
        assert dt is not None

    def test_parse_datetime_already_aware(self) -> None:
        dt_in = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = datetimes.parse_datetime(dt_in)
        assert result == dt_in

    def test_ensure_utc_naive(self) -> None:
        naive = datetime(2026, 1, 1, 12, 0, 0)
        result = datetimes.ensure_utc(naive)
        assert result.tzinfo == UTC

    def test_utc_now_is_aware(self) -> None:
        now = datetimes.utc_now()
        assert now.tzinfo == UTC
