"""Test coverage for Analytics.get_overview() (T7)."""

import os
from datetime import UTC, datetime, timedelta

import model
import pytest
from service.analytics import Analytics
from tortoise import Tortoise


@pytest.fixture
def analytics():
    return Analytics()


@pytest.mark.asyncio
async def test_overview_empty_no_trades(tmp_path, monkeypatch, analytics) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    result = await analytics.get_overview()

    assert result["summary"]["total_trades"] == 0
    assert result["summary"]["win_rate"] == 0.0
    assert result["summary"]["total_profit"] == 0.0
    assert result["heatmap_daily"] == []
    assert result["heatmap_weekly"] == []
    assert result["per_symbol"] == []
    assert result["duration_extremes"]["longest"] == []
    assert result["duration_extremes"]["shortest"] == []
    assert result["drawdown"]["max_drawdown"] == 0.0

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_overview_summary_with_trades(tmp_path, monkeypatch, analytics) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.now(UTC)
    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        deal_id="deal-1",
        profit=5.0,
        profit_percent=10.0,
        cost=50.0,
        open_date=(now - timedelta(hours=6)).isoformat(),
        close_date=now.isoformat(),
        duration="6:00:00",
        close_reason="take_profit",
    )
    await model.ClosedTrades.create(
        symbol="ETH/USDT",
        deal_id="deal-2",
        profit=-2.0,
        profit_percent=-4.0,
        cost=25.0,
        open_date=(now - timedelta(hours=3)).isoformat(),
        close_date=(now - timedelta(hours=2)).isoformat(),
        duration="1:00:00",
        close_reason="stop_loss",
    )

    result = await analytics.get_overview()

    summary = result["summary"]
    assert summary["total_trades"] == 2
    assert summary["profit_trades"] == 1
    assert summary["loss_trades"] == 1
    assert summary["win_rate"] == pytest.approx(50.0)
    assert summary["total_profit"] == pytest.approx(3.0)
    assert summary["avg_profit"] == pytest.approx(1.5)
    assert summary["total_cost"] == pytest.approx(75.0)

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_overview_heatmap_daily(tmp_path, monkeypatch, analytics) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.now(UTC)
    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        profit=5.0,
        close_date=now.isoformat(),
    )
    await model.ClosedTrades.create(
        symbol="ETH/USDT",
        profit=3.0,
        close_date=now.isoformat(),
    )
    yesterday = now - timedelta(days=1)
    await model.ClosedTrades.create(
        symbol="SOL/USDT",
        profit=2.0,
        close_date=yesterday.isoformat(),
    )

    result = await analytics.get_overview()

    assert len(result["heatmap_daily"]) >= 1
    for entry in result["heatmap_daily"]:
        assert "timestamp" in entry
        assert "value" in entry

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_overview_per_symbol(tmp_path, monkeypatch, analytics) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.now(UTC)
    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        profit=5.0,
        profit_percent=10.0,
        close_date=now.isoformat(),
    )
    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        profit=-1.0,
        profit_percent=-2.0,
        close_date=(now - timedelta(hours=1)).isoformat(),
    )
    await model.ClosedTrades.create(
        symbol="ETH/USDT",
        profit=8.0,
        profit_percent=16.0,
        close_date=now.isoformat(),
    )

    result = await analytics.get_overview()

    symbols = result["per_symbol"]
    assert len(symbols) == 2
    symbol_map = {s["symbol"]: s for s in symbols}
    assert symbol_map["BTC/USDT"]["trades"] == 2
    assert symbol_map["ETH/USDT"]["trades"] == 1

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_overview_duration_extremes(tmp_path, monkeypatch, analytics) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.now(UTC)
    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        profit=5.0,
        open_date=(now - timedelta(hours=10)).isoformat(),
        close_date=now.isoformat(),
        duration="10:00:00",
    )
    await model.ClosedTrades.create(
        symbol="ETH/USDT",
        profit=3.0,
        open_date=(now - timedelta(hours=1)).isoformat(),
        close_date=(now - timedelta(minutes=30)).isoformat(),
        duration="0:30:00",
    )

    result = await analytics.get_overview()

    extremes = result["duration_extremes"]
    assert len(extremes["longest"]) >= 1
    assert len(extremes["shortest"]) >= 1
    assert extremes["longest"][0]["symbol"] == "BTC/USDT"
    assert extremes["shortest"][0]["symbol"] == "ETH/USDT"

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_overview_drawdown_computation(tmp_path, monkeypatch, analytics) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        profit=10.0,
        close_date=(base + timedelta(hours=1)).isoformat(),
    )
    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        profit=10.0,
        close_date=(base + timedelta(hours=2)).isoformat(),
    )
    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        profit=-15.0,
        close_date=(base + timedelta(hours=3)).isoformat(),
    )

    result = await analytics.get_overview()

    assert result["drawdown"]["max_drawdown"] > 0
    assert result["drawdown"]["max_drawdown_percent"] > 0

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_overview_distribution(tmp_path, monkeypatch, analytics) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.now(UTC)
    for i, pct in enumerate([-10, -5, 0, 5, 10, 20, 30, 40, 50, 60]):
        await model.ClosedTrades.create(
            symbol=f"SYM{i}/USDT",
            profit=pct,
            profit_percent=pct,
            close_date=(now - timedelta(hours=i)).isoformat(),
        )

    result = await analytics.get_overview()

    dist = result["distribution"]
    assert len(dist["bins"]) == 10
    total_in_bins = sum(b["count"] for b in dist["bins"])
    assert total_in_bins == 10
    assert dist["best"] == 60.0
    assert dist["worst"] == -10.0

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_overview_2_year_window_excludes_old(
    tmp_path, monkeypatch, analytics
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.now(UTC)
    recent = now - timedelta(days=1)
    very_old = now - timedelta(days=730)

    await model.ClosedTrades.create(
        symbol="BTC/USDT", profit=5.0, close_date=recent.isoformat()
    )
    await model.ClosedTrades.create(
        symbol="ETH/USDT", profit=3.0, close_date=very_old.isoformat()
    )

    result = await analytics.get_overview()

    assert result["summary"]["total_trades"] == 1

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_overview_mixed_null_fields(tmp_path, monkeypatch, analytics) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.now(UTC)
    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        profit=None,
        profit_percent=None,
        cost=None,
        open_date=None,
        close_date=now.isoformat(),
        duration=None,
    )

    result = await analytics.get_overview()

    assert result["summary"]["total_trades"] == 1
    assert result["summary"]["total_profit"] == 0.0

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_oversview_empty_returns_safe_defaults(analytics) -> None:
    result = Analytics._empty()
    assert result["summary"]["total_trades"] == 0
    assert result["heatmap_daily"] == []
    assert result["duration_extremes"] == {"longest": [], "shortest": []}
