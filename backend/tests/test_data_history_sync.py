import os
import types

import pytest
import service.data as data_module
from service.data import Data
from service.data_history_sync import (
    HistorySyncState,
    HistorySyncWindow,
    plan_boundary_fetch_starts,
)
from tortoise import Tortoise


def _make_candle(timestamp: int, close: float) -> list[float]:
    return [
        float(timestamp),
        close - 1.0,
        close + 1.0,
        close - 2.0,
        close,
        10.0,
    ]


def test_plan_boundary_fetch_starts_prefers_missing_edges_only() -> None:
    window = HistorySyncWindow.build(
        required_since=1000,
        required_until=4000,
        timeframe_ms=1000,
    )

    fetch_starts = plan_boundary_fetch_starts(
        window=window,
        stored_timestamps={2000, 3000},
    )

    assert fetch_starts == [1000, 4000]


def test_history_sync_state_tracks_first_available_and_missing_count() -> None:
    window = HistorySyncWindow.build(
        required_since=1000,
        required_until=4000,
        timeframe_ms=1000,
    )
    state = HistorySyncState(stored_timestamps={3000, 4000})

    state.record_fetch(
        fetched_timestamps={3000, 4000},
        inserted_timestamps={3000, 4000},
    )

    assert state.earliest_available_timestamp == 3000
    assert state.is_required_complete(window) is False
    assert state.is_complete_from_first_available(window) is True
    assert state.missing_count(window) == 2


@pytest.mark.asyncio
async def test_history_sync_backfills_only_missing_newer_boundary(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model

    await model.Tickers.create(
        timestamp=1000,
        symbol="BTC/USDC",
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10.0,
    )
    await model.Tickers.create(
        timestamp=2000,
        symbol="BTC/USDC",
        open=2.0,
        high=3.0,
        low=1.5,
        close=2.5,
        volume=10.0,
    )

    data = Data()
    fetch_calls: list[int] = []

    async def fake_get_history_for_symbol(
        config: dict, symbol: str, timeframe: str, limit: int = 1, since: int = 0
    ):
        fetch_calls.append(int(since))
        return [_make_candle(3000, 3.5)]

    async def fake_close() -> None:
        return None

    monkeypatch.setattr(
        data_module,
        "resolve_required_history_window",
        lambda history_data, timeframe, since_ms=None: (1000, 3000, 1000),
    )
    data.exchange = types.SimpleNamespace(
        get_history_for_symbol=fake_get_history_for_symbol,
        close=fake_close,
    )

    success = await data.add_history_data_for_symbol(
        symbol="BTC/USDC",
        history_data=1,
        config={"timeframe": "1s"},
    )

    rows = (
        await model.Tickers.filter(symbol="BTC/USDC")
        .order_by("timestamp")
        .values_list("timestamp", flat=True)
    )

    assert success is True
    assert fetch_calls == [3000]
    assert [int(float(row)) for row in rows] == [1000, 2000, 3000]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_history_sync_falls_back_to_full_refill_for_internal_gap(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model

    await model.Tickers.create(
        timestamp=1000,
        symbol="BTC/USDC",
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10.0,
    )
    await model.Tickers.create(
        timestamp=3000,
        symbol="BTC/USDC",
        open=3.0,
        high=4.0,
        low=2.5,
        close=3.5,
        volume=10.0,
    )

    data = Data()
    fetch_calls: list[int] = []

    async def fake_get_history_for_symbol(
        config: dict, symbol: str, timeframe: str, limit: int = 1, since: int = 0
    ):
        fetch_calls.append(int(since))
        return [
            _make_candle(1000, 1.5),
            _make_candle(2000, 2.5),
            _make_candle(3000, 3.5),
        ]

    async def fake_close() -> None:
        return None

    monkeypatch.setattr(
        data_module,
        "resolve_required_history_window",
        lambda history_data, timeframe, since_ms=None: (1000, 3000, 1000),
    )
    data.exchange = types.SimpleNamespace(
        get_history_for_symbol=fake_get_history_for_symbol,
        close=fake_close,
    )

    success = await data.add_history_data_for_symbol(
        symbol="BTC/USDC",
        history_data=1,
        config={"timeframe": "1s"},
    )

    rows = (
        await model.Tickers.filter(symbol="BTC/USDC")
        .order_by("timestamp")
        .values_list("timestamp", flat=True)
    )

    assert success is True
    assert fetch_calls == [1000]
    assert [int(float(row)) for row in rows] == [1000, 2000, 3000]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_history_sync_preserves_existing_rows_when_exchange_fetch_fails(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model

    await model.Tickers.create(
        timestamp=1000,
        symbol="BTC/USDC",
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10.0,
    )

    data = Data()
    fetch_calls: list[int] = []

    async def fake_get_history_for_symbol(
        config: dict, symbol: str, timeframe: str, limit: int = 1, since: int = 0
    ):
        fetch_calls.append(int(since))
        return []

    async def fake_close() -> None:
        return None

    monkeypatch.setattr(
        data_module,
        "resolve_required_history_window",
        lambda history_data, timeframe, since_ms=None: (1000, 3000, 1000),
    )
    data.exchange = types.SimpleNamespace(
        get_history_for_symbol=fake_get_history_for_symbol,
        close=fake_close,
    )

    success = await data.add_history_data_for_symbol(
        symbol="BTC/USDC",
        history_data=1,
        config={"timeframe": "1s"},
    )

    rows = (
        await model.Tickers.filter(symbol="BTC/USDC")
        .order_by("timestamp")
        .values_list("timestamp", flat=True)
    )

    assert success is False
    assert fetch_calls == [2000, 1000]
    assert [int(float(row)) for row in rows] == [1000]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_history_sync_accepts_complete_window_since_first_available_candle(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model

    data = Data()
    fetch_calls: list[int] = []

    async def fake_get_history_for_symbol(
        config: dict, symbol: str, timeframe: str, limit: int = 1, since: int = 0
    ):
        fetch_calls.append(int(since))
        return [
            _make_candle(3000, 3.5),
            _make_candle(4000, 4.5),
        ]

    async def fake_close() -> None:
        return None

    monkeypatch.setattr(
        data_module,
        "resolve_required_history_window",
        lambda history_data, timeframe, since_ms=None: (1000, 4000, 1000),
    )
    data.exchange = types.SimpleNamespace(
        get_history_for_symbol=fake_get_history_for_symbol,
        close=fake_close,
    )

    success = await data.add_history_data_for_symbol(
        symbol="BTC/USDC",
        history_data=1,
        config={"timeframe": "1s"},
    )

    rows = (
        await model.Tickers.filter(symbol="BTC/USDC")
        .order_by("timestamp")
        .values_list("timestamp", flat=True)
    )

    assert success is True
    assert fetch_calls == [1000]
    assert [int(float(row)) for row in rows] == [3000, 4000]

    await Tortoise.close_connections()
