"""Regression tests for _parse_duration_hours extraction (T6)."""

import os

import pytest
from service.autopilot_memory import _parse_duration_hours


@pytest.mark.asyncio
async def test_parse_duration_hours_from_iso_dates(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    duration = _parse_duration_hours(
        "0:00:00",
        open_date="2026-01-01T10:00:00+00:00",
        close_date="2026-01-01T14:00:00+00:00",
    )
    assert duration == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_parse_duration_hours_from_string_timedelta(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    duration = _parse_duration_hours("3:30:00", open_date=None, close_date=None)
    assert duration == pytest.approx(3.5)


@pytest.mark.asyncio
async def test_parse_duration_hours_from_numeric_seconds(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    duration = _parse_duration_hours(7200.0, open_date=None, close_date=None)
    assert duration == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_parse_duration_hours_from_string_numeric(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    duration = _parse_duration_hours("7200.0", open_date=None, close_date=None)
    assert duration == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_parse_duration_hours_none_fallback(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    duration = _parse_duration_hours(None, open_date=None, close_date=None)
    assert duration is None


@pytest.mark.asyncio
async def test_parse_duration_hours_inverted_dates_returns_zero(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    duration = _parse_duration_hours(
        "0:00:00",
        open_date="2026-01-02T10:00:00+00:00",
        close_date="2026-01-01T10:00:00+00:00",
    )
    assert duration == 0.0
