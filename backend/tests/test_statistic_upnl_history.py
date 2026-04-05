import os
import types
from datetime import datetime, timedelta

import model
import pytest
from service.config import Config
from service.statistic import Statistic
from tortoise import Tortoise


@pytest.mark.asyncio
async def test_get_upnl_history_all_returns_ordered_rows(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    first = datetime(2026, 2, 10, 10, 0, 0)
    second = first + timedelta(minutes=1)

    await model.UpnlHistory.create(
        timestamp=second,
        upnl=2.0,
        profit_overall=2.5,
        funds_locked=6.0,
    )
    await model.UpnlHistory.create(
        timestamp=first,
        upnl=1.0,
        profit_overall=1.5,
        funds_locked=5.0,
    )

    statistic = Statistic()
    data = await statistic.get_upnl_history_all()

    assert len(data) == 2
    assert data[0]["timestamp"] == "2026-02-10 10:00:00"
    assert data[0]["profit_overall"] == 1.5
    assert data[0]["funds_locked"] == 5.0
    assert data[1]["timestamp"] == "2026-02-10 10:01:00"
    assert data[1]["profit_overall"] == 2.5
    assert data[1]["funds_locked"] == 6.0

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_store_upnl_snapshot_applies_sampling_interval(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    statistic = Statistic()
    statistic.snapshot_interval_seconds = 10_000

    await statistic._store_upnl_snapshot(
        {"upnl": 1.0, "profit_overall": 1.0, "funds_locked": 4.0}
    )
    await statistic._store_upnl_snapshot(
        {"upnl": 2.0, "profit_overall": 2.0, "funds_locked": 5.0}
    )

    rows = await model.UpnlHistory.all()
    assert len(rows) == 1
    assert rows[0].upnl == 1.0
    assert rows[0].funds_locked == 4.0

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_profit_overall_uses_upnl_when_no_closed_trades(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.OpenTrades.create(symbol="BTC/USDT", profit=12.5, cost=42.0)

    statistic = Statistic()
    statistic.autopilot.resolve_runtime_state = _async_autopilot_state(
        {
            "mode": "low",
            "effective_max_bots": 5,
            "green_phase_detected": True,
            "green_phase_active": True,
            "green_phase_extra_deals": 1,
            "green_phase_strength": 1.7,
            "green_phase_block_reason": None,
            "green_phase_ramp_ready": True,
        }
    )
    data = await statistic.get_profit()

    assert data["upnl"] == 12.5
    assert data["profit_overall"] == 12.5
    assert data["funds_locked"] == 42.0
    assert data["autopilot"] == "low"
    assert data["autopilot_effective_max_bots"] == 5
    assert data["autopilot_green_phase_active"] is True

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_profit_overall_timeline_returns_data(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.utcnow()
    await model.UpnlHistory.create(
        timestamp=now - timedelta(hours=2),
        upnl=1.0,
        profit_overall=10.0,
        funds_locked=100.0,
    )
    await model.UpnlHistory.create(
        timestamp=now - timedelta(hours=1),
        upnl=2.0,
        profit_overall=11.0,
        funds_locked=101.0,
    )
    await model.UpnlHistory.create(
        timestamp=now,
        upnl=3.0,
        profit_overall=12.0,
        funds_locked=102.0,
    )

    statistic = Statistic()
    timeline = await statistic.get_profit_overall_timeline()

    assert len(timeline) >= 1
    assert "timestamp" in timeline[-1]
    assert "profit_overall" in timeline[-1]
    assert "funds_locked" in timeline[-1]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_profits_overall_accepts_second_precision_timestamps(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        profit=5.0,
        close_date="2026-03-10 10:00:00",
    )
    await model.ClosedTrades.create(
        symbol="ETH/USDT",
        profit=7.0,
        close_date="2026-03-10 11:00:00",
    )

    statistic = Statistic()
    reference_timestamp = int(datetime(2026, 3, 31, 23, 59, 59).timestamp())
    daily = await statistic.get_profits_overall(reference_timestamp, "daily")

    assert daily is not None
    assert daily["2026-03-10"] == 12.0

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_update_statistic_data_uses_fallback_when_base_order_missing() -> None:
    statistic = Statistic()
    captured: dict[str, object] = {}

    async def fake_get_trade_by_ordertype(
        symbol: str, baseorder: bool = False
    ) -> list[dict[str, object]]:
        return []

    async def fake_update_open_trades(payload: dict[str, object], symbol: str) -> None:
        captured["payload"] = payload
        captured["symbol"] = symbol

    statistic.trades.get_trade_by_ordertype = fake_get_trade_by_ordertype
    statistic.trades.update_open_trades = fake_update_open_trades

    stats = {
        "type": "tp_check",
        "symbol": "BTC/USDC",
        "total_amount": 2.0,
        "total_cost": 20.0,
        "current_price": 12.0,
        "tp_price": 11.0,
        "avg_price": 10.0,
        "actual_pnl": 20.0,
        "sell": False,
    }
    await statistic.update_statistic_data(stats)

    assert captured["symbol"] == "BTC/USDC"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert float(payload["open_date"]) > 1_000_000_000_000


@pytest.mark.asyncio
async def test_update_statistic_data_updates_open_trade_during_tp_sell() -> None:
    statistic = Statistic()
    captured: dict[str, object] = {}

    async def fake_get_trade_by_ordertype(
        symbol: str, baseorder: bool = False
    ) -> list[dict[str, object]]:
        return [{"timestamp": 1_700_000_000_000}]

    async def fake_update_open_trades(payload: dict[str, object], symbol: str) -> None:
        captured["payload"] = payload
        captured["symbol"] = symbol

    statistic.trades.get_trade_by_ordertype = fake_get_trade_by_ordertype
    statistic.trades.update_open_trades = fake_update_open_trades

    stats = {
        "type": "tp_check",
        "symbol": "BTC/USDC",
        "total_amount": 5.0,
        "total_cost": 100.0,
        "current_price": 25.0,
        "tp_price": 24.0,
        "avg_price": 20.0,
        "actual_pnl": 25.0,
        "sell": True,
    }
    await statistic.update_statistic_data(stats)

    assert captured["symbol"] == "BTC/USDC"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["current_price"] == 25.0
    assert payload["profit"] == 25.0
    assert payload["profit_percent"] == 25.0
    assert float(payload["open_date"]) == 1_700_000_000_000.0


@pytest.mark.asyncio
async def test_get_profit_for_dashboard_uses_available_quote_override(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    statistic = Statistic()

    async def fake_profit_base() -> dict[str, object]:
        return {
            "upnl": 12.5,
            "profit_overall": 14.0,
            "funds_locked": 42.0,
            "profit_week": {},
            "profit_overall_timestamp": "2026-03-18 12:00:00",
        }

    async def fake_resolve_runtime_state(*_args, **kwargs) -> dict[str, object]:
        captured["available_quote"] = kwargs.get("available_quote")
        return {
            "mode": "low",
            "effective_max_bots": 5,
            "green_phase_detected": True,
            "green_phase_active": True,
            "green_phase_extra_deals": 1,
            "green_phase_strength": 1.7,
            "green_phase_block_reason": None,
            "green_phase_ramp_ready": True,
        }

    async def fake_config_instance():
        return types.SimpleNamespace(snapshot=lambda: {"autopilot": True})

    monkeypatch.setattr(statistic, "_get_profit_base_cached", fake_profit_base)
    monkeypatch.setattr(
        statistic.autopilot,
        "resolve_runtime_state",
        fake_resolve_runtime_state,
    )
    monkeypatch.setattr(Config, "instance", staticmethod(fake_config_instance))

    data = await statistic.get_profit_for_dashboard(321.5)

    assert data["funds_available"] == 321.5
    assert data["autopilot_effective_max_bots"] == 5
    assert captured["available_quote"] == 321.5


def _async_autopilot_state(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner
