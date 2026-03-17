import os
from datetime import datetime, timedelta, timezone

import model
import pytest
from service.green_phase import GreenPhaseService
from tortoise import Tortoise


def _build_config(**overrides):
    config = {
        "autopilot": True,
        "autopilot_max_fund": 1_000,
        "autopilot_green_phase_enabled": True,
        "autopilot_green_phase_ramp_days": 10,
        "autopilot_green_phase_eval_interval_sec": 60,
        "autopilot_green_phase_window_minutes": 60,
        "autopilot_green_phase_min_profitable_close_ratio": 0.8,
        "autopilot_green_phase_speed_multiplier": 1.5,
        "autopilot_green_phase_exit_multiplier": 1.15,
        "autopilot_green_phase_max_extra_deals": 2,
        "autopilot_green_phase_confirm_cycles": 1,
        "autopilot_green_phase_release_cycles": 2,
        "autopilot_green_phase_max_locked_fund_percent": 85,
        "currency": "USDT",
        "bo": 100,
        "so": 50,
        "mstc": 2,
        "os": 1.0,
        "dynamic_dca": False,
        "max_bots": 3,
    }
    config.update(overrides)
    return config


def _utc_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_green_phase_detects_fast_profitable_close_burst(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.now(timezone.utc)
    for day_offset in range(7):
        await model.ClosedTrades.create(
            symbol=f"OLD{day_offset}/USDT",
            profit=1.0,
            close_date=_utc_iso(now - timedelta(days=day_offset + 2)),
        )
    for minute_offset in (5, 15, 35):
        await model.ClosedTrades.create(
            symbol=f"FAST{minute_offset}/USDT",
            profit=1.0,
            close_date=_utc_iso(now - timedelta(minutes=minute_offset)),
        )

    service = GreenPhaseService()
    config = _build_config()
    service.on_config_change(config)

    async def fake_get_free_balance_for_asset(*_args, **_kwargs) -> float:
        return 1_000.0

    service.exchange.get_free_balance_for_asset = fake_get_free_balance_for_asset

    await service.refresh_state()
    state = service.get_state()
    override = await service.get_override(config, funds_locked=100.0, base_max_bots=3)

    assert state["ramp_ready"] is True
    assert state["green_phase_detected"] is True
    assert state["recommended_extra_deals"] == 2
    assert override["green_phase_active"] is True
    assert override["effective_extra_deals"] == 2
    assert override["effective_max_bots"] == 5

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_green_phase_blocks_extra_deals_when_reserve_is_too_small(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.now(timezone.utc)
    for day_offset in range(7):
        await model.ClosedTrades.create(
            symbol=f"OLD{day_offset}/USDT",
            profit=1.0,
            close_date=_utc_iso(now - timedelta(days=day_offset + 2)),
        )
    for minute_offset in (5, 15, 35):
        await model.ClosedTrades.create(
            symbol=f"FAST{minute_offset}/USDT",
            profit=1.0,
            close_date=_utc_iso(now - timedelta(minutes=minute_offset)),
        )

    await model.OpenTrades.create(symbol="OPEN/USDT", so_count=0, cost=100.0)

    service = GreenPhaseService()
    config = _build_config()
    service.on_config_change(config)

    async def fake_get_free_balance_for_asset(*_args, **_kwargs) -> float:
        return 150.0

    service.exchange.get_free_balance_for_asset = fake_get_free_balance_for_asset

    await service.refresh_state()
    override = await service.get_override(config, funds_locked=100.0, base_max_bots=3)

    assert override["green_phase_detected"] is True
    assert override["green_phase_active"] is False
    assert override["effective_extra_deals"] == 0
    assert override["effective_max_bots"] == 3
    assert override["guardrail_block_reason"] == "reserve_shortfall"

    await Tortoise.close_connections()
