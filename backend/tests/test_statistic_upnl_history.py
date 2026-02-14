import os
from datetime import datetime, timedelta

import model
import pytest
from service.statistic import Statistic
from tortoise import Tortoise


@pytest.mark.asyncio
async def test_get_upnl_history_all_returns_ordered_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    first = datetime(2026, 2, 10, 10, 0, 0)
    second = first + timedelta(minutes=1)

    await model.UpnlHistory.create(timestamp=second, upnl=2.0, profit_overall=2.5)
    await model.UpnlHistory.create(timestamp=first, upnl=1.0, profit_overall=1.5)

    statistic = Statistic()
    data = await statistic.get_upnl_history_all()

    assert len(data) == 2
    assert data[0]["timestamp"] == "2026-02-10 10:00:00"
    assert data[0]["profit_overall"] == 1.5
    assert data[1]["timestamp"] == "2026-02-10 10:01:00"
    assert data[1]["profit_overall"] == 2.5

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_store_upnl_snapshot_applies_sampling_interval(tmp_path, monkeypatch):
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    statistic = Statistic()
    statistic.snapshot_interval_seconds = 10_000

    await statistic._store_upnl_snapshot({"upnl": 1.0, "profit_overall": 1.0})
    await statistic._store_upnl_snapshot({"upnl": 2.0, "profit_overall": 2.0})

    rows = await model.UpnlHistory.all()
    assert len(rows) == 1
    assert rows[0].upnl == 1.0

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_profit_overall_uses_upnl_when_no_closed_trades(tmp_path, monkeypatch):
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.OpenTrades.create(symbol="BTC/USDT", profit=12.5)

    statistic = Statistic()
    data = await statistic.get_profit()

    assert data["upnl"] == 12.5
    assert data["profit_overall"] == 12.5

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_profit_overall_timeline_returns_data(tmp_path, monkeypatch):
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.utcnow()
    await model.UpnlHistory.create(
        timestamp=now - timedelta(hours=2), upnl=1.0, profit_overall=10.0
    )
    await model.UpnlHistory.create(
        timestamp=now - timedelta(hours=1), upnl=2.0, profit_overall=11.0
    )
    await model.UpnlHistory.create(timestamp=now, upnl=3.0, profit_overall=12.0)

    statistic = Statistic()
    timeline = await statistic.get_profit_overall_timeline()

    assert len(timeline) >= 1
    assert "timestamp" in timeline[-1]
    assert "profit_overall" in timeline[-1]

    await Tortoise.close_connections()
