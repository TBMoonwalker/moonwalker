"""Test coverage for Analytics.get_overview() (T7)."""

import os
from datetime import UTC, datetime, timedelta

import model
import pytest
from cachetools import TTLCache
from service import analytics as analytics_module
from service.analytics import Analytics
from tortoise import Tortoise


@pytest.fixture
def analytics():
    return Analytics()


@pytest.mark.asyncio
async def test_mode_scoped_analytics_excludes_unattributed_and_other_modes(
    tmp_path, analytics
):
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'modes.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    now = datetime.now(UTC).isoformat()
    await model.ClosedTrades.create(
        symbol="BTC/USDC", lifecycle_mode="classic_dca", profit=2, close_date=now
    )
    await model.ClosedTrades.create(
        symbol="ETH/USDC", lifecycle_mode="accumulation", profit=9, close_date=now
    )
    await model.ClosedTrades.create(symbol="SOL/USDC", profit=4, close_date=now)
    dca = await analytics.get_overview("dynamic_dca")
    unknown = await analytics.get_overview("unknown")
    legacy = await analytics.get_overview()
    assert dca["summary"]["total_profit"] == 2
    assert dca["unattributed_trades"] == 1
    assert unknown["summary"]["total_profit"] == 4
    assert legacy["summary"]["total_profit"] == 15
    await Tortoise.close_connections()


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
async def test_overview_heatmap_weekly_uses_iso_week_start(
    tmp_path, monkeypatch, analytics
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monday = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        profit=5.0,
        close_date=monday.isoformat(),
    )
    await model.ClosedTrades.create(
        symbol="ETH/USDT",
        profit=3.0,
        close_date=(monday + timedelta(days=2)).isoformat(),
    )

    result = await analytics.get_overview()

    assert result["heatmap_weekly"] == [
        {
            "timestamp": int(
                monday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                * 1000
            ),
            "value": 2,
        }
    ]

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
    assert all(not (b["min"] < 0 < b["max"]) for b in dist["bins"])
    assert [b["label"] for b in dist["bins"]] == [
        "Loss",
        "Loss",
        "Breakeven",
        "Profit",
        "Profit",
        "Profit",
        "Profit",
        "Profit",
        "Profit",
        "Profit",
    ]
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


def _install_aggregation_counter(monkeypatch) -> dict[str, int]:
    """Count invocations of the module-level aggregation pass."""
    calls: dict[str, int] = {"count": 0}
    original = analytics_module.compute_stats_from_trades

    def counting(rows: list) -> dict:
        calls["count"] += 1
        return original(rows)

    monkeypatch.setattr(analytics_module, "compute_stats_from_trades", counting)
    return calls


async def _init_db_with_one_closed_trade(tmp_path) -> None:
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'cache.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    now = datetime.now(UTC).isoformat()
    await model.ClosedTrades.create(
        symbol="BTC/USDC", lifecycle_mode="classic_dca", profit=2, close_date=now
    )


@pytest.mark.asyncio
async def test_overview_single_aggregation_within_ttl(
    tmp_path, monkeypatch, analytics
) -> None:
    """A second call inside the TTL returns the cached object, no re-aggregation."""
    await _init_db_with_one_closed_trade(tmp_path)
    calls = _install_aggregation_counter(monkeypatch)

    first = await analytics.get_overview()
    second = await analytics.get_overview()

    assert calls["count"] == 1
    assert first is second
    assert first["summary"]["total_trades"] == 1
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_overview_cache_isolated_per_mode(tmp_path, analytics) -> None:
    """Modes None/dynamic_dca/unknown keep independent cache entries."""
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'modes-cache.sqlite'}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()
    now = datetime.now(UTC).isoformat()
    await model.ClosedTrades.create(
        symbol="BTC/USDC", lifecycle_mode="classic_dca", profit=2, close_date=now
    )
    await model.ClosedTrades.create(
        symbol="ETH/USDC", lifecycle_mode="accumulation", profit=9, close_date=now
    )

    dca_first = await analytics.get_overview("dynamic_dca")
    unknown = await analytics.get_overview("unknown")
    dca_second = await analytics.get_overview("dynamic_dca")
    legacy = await analytics.get_overview()

    assert dca_first is dca_second
    assert dca_first is not unknown
    assert dca_first["summary"]["total_profit"] == 2
    assert unknown["summary"]["total_profit"] == 0
    assert legacy["summary"]["total_profit"] == 11
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_overview_cache_clear_forces_recompute(
    tmp_path, monkeypatch, analytics
) -> None:
    """The cache_clear seam forces a fresh aggregation for future callers."""
    await _init_db_with_one_closed_trade(tmp_path)
    calls = _install_aggregation_counter(monkeypatch)

    first = await analytics.get_overview()
    assert calls["count"] == 1
    await analytics.get_overview.cache_clear()
    second = await analytics.get_overview()

    assert calls["count"] == 2
    assert first is not second
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_overview_ttl_contract_pinned(tmp_path, analytics) -> None:
    """The staleness contract pins TTL=60 and cached-object identity."""
    assert analytics_module.ANALYTICS_CACHE_TTL_SECONDS == 60
    await _init_db_with_one_closed_trade(tmp_path)

    first = await analytics.get_overview()
    second = await analytics.get_overview()

    assert first is second
    assert first["summary"]["total_trades"] == 1
    await Tortoise.close_connections()


def _overview_cache() -> TTLCache:
    """Return the TTLCache the get_overview decorator closes over."""
    closure = Analytics.get_overview.__closure__ or ()
    for cell in closure:
        if isinstance(cell.cell_contents, TTLCache):
            return cell.cell_contents
    raise AssertionError("get_overview TTL cache not found in decorator closure")


# Value: protects=get_overview TTL expiry at the 60s staleness bound
# (a call after the TTL recomputes into a new object); fails_when=the
# ttl= argument is dropped or the cache stops expiring; why_new=existing
# tests observe only the in-TTL window and the constant pin; seam=none
# (reads the existing decorator closure, no production hook);
# no_claim=deterministic clock swap inside cachetools' private _Timer -
# real wall-clock expiry is not waited out.
@pytest.mark.asyncio
async def test_overview_cache_expires_after_ttl(
    tmp_path, monkeypatch, analytics
) -> None:
    """A call after the 60s staleness bound recomputes, not reuses the cache."""
    await _init_db_with_one_closed_trade(tmp_path)
    calls = _install_aggregation_counter(monkeypatch)
    cache = _overview_cache()
    # cachetools 8 wraps the timer in a private _Timer behind a read-only
    # property, so swap the wrapped clock function directly. The fake clock
    # is frozen at the insertion instant, keeping the expiry deterministic.
    real_clock = cache.timer
    clock = {"base": real_clock(), "offset": 0.0}

    def fake_clock() -> float:
        return clock["base"] + clock["offset"]

    monkeypatch.setattr(cache.timer, "_Timer__timer", fake_clock)

    first = await analytics.get_overview()
    assert calls["count"] == 1
    clock["offset"] = float(analytics_module.ANALYTICS_CACHE_TTL_SECONDS) + 1.0
    second = await analytics.get_overview()

    assert calls["count"] == 2
    assert second is not first
    await Tortoise.close_connections()
