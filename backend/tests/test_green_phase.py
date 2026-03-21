import os
from datetime import datetime, timedelta, timezone

import model
import pytest
from service.green_phase import GreenPhaseService
from service.green_phase_logic import (
    analyze_green_phase_rows,
    apply_green_phase_guardrails,
    build_green_phase_override_base,
    build_green_phase_settings,
)
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


def _build_closed_trade_rows(now: datetime) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    for day_offset in range(7):
        rows.append((_utc_iso(now - timedelta(days=day_offset + 2)), 1.0))
    for minute_offset in (5, 15, 35):
        rows.append((_utc_iso(now - timedelta(minutes=minute_offset)), 1.0))
    return rows


def test_green_phase_analysis_requires_confirm_cycles_before_detection() -> None:
    now = datetime.now(timezone.utc)
    settings = build_green_phase_settings(
        _build_config(autopilot_green_phase_confirm_cycles=2)
    )
    rows = _build_closed_trade_rows(now)

    first, confirm_counter, release_counter = analyze_green_phase_rows(
        rows,
        now=now,
        settings=settings,
        current_detected=False,
        confirm_counter=0,
        release_counter=0,
        min_ramp_total_closes=GreenPhaseService.MIN_RAMP_TOTAL_CLOSES,
        min_ramp_profitable_closes=GreenPhaseService.MIN_RAMP_PROFITABLE_CLOSES,
        min_recent_profitable_closes=GreenPhaseService.MIN_RECENT_PROFITABLE_CLOSES,
    )

    second, confirm_counter, release_counter = analyze_green_phase_rows(
        rows,
        now=now,
        settings=settings,
        current_detected=False,
        confirm_counter=confirm_counter,
        release_counter=release_counter,
        min_ramp_total_closes=GreenPhaseService.MIN_RAMP_TOTAL_CLOSES,
        min_ramp_profitable_closes=GreenPhaseService.MIN_RAMP_PROFITABLE_CLOSES,
        min_recent_profitable_closes=GreenPhaseService.MIN_RECENT_PROFITABLE_CLOSES,
    )

    assert first.ramp_ready is True
    assert first.green_phase_detected is False
    assert confirm_counter == 0
    assert second.green_phase_detected is True


def test_green_phase_guardrails_block_when_locked_fund_limit_is_exceeded() -> None:
    settings = build_green_phase_settings(
        _build_config(
            autopilot_max_fund=1_000,
            autopilot_green_phase_max_locked_fund_percent=70,
            autopilot_green_phase_max_extra_deals=2,
            bo=100,
        )
    )
    result = build_green_phase_override_base(
        {
            "enabled": True,
            "ramp_ready": True,
            "green_phase_detected": True,
            "green_phase_active": False,
            "phase_strength": 2.0,
            "baseline_profitable_closes_per_hour": 0.1,
            "recent_profitable_closes_per_hour": 0.4,
            "recent_profitable_close_ratio": 1.0,
            "recent_total_closes": 3,
            "recent_profitable_closes": 3,
            "recommended_extra_deals": 2,
            "effective_extra_deals": 0,
            "effective_max_bots": 0,
            "guardrail_block_reason": None,
            "last_evaluated_at": "2026-03-18 12:00:00",
        },
        base_max_bots=3,
    )

    guarded = apply_green_phase_guardrails(
        result,
        settings=settings,
        funds_locked=650.0,
        base_max_bots=3,
        current_reserve=0.0,
        full_trade_budget=100.0,
        available_quote=10_000.0,
    )

    assert guarded["green_phase_active"] is False
    assert guarded["effective_extra_deals"] == 0
    assert guarded["guardrail_block_reason"] == "locked_fund_guardrail"


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


@pytest.mark.asyncio
async def test_green_phase_uses_provided_available_quote_without_exchange_fetch(
    monkeypatch,
) -> None:
    service = GreenPhaseService()
    service._state = {
        "enabled": True,
        "ramp_ready": True,
        "green_phase_detected": True,
        "green_phase_active": False,
        "phase_strength": 2.0,
        "baseline_profitable_closes_per_hour": 0.1,
        "recent_profitable_closes_per_hour": 0.4,
        "recent_profitable_close_ratio": 1.0,
        "recent_total_closes": 3,
        "recent_profitable_closes": 3,
        "recommended_extra_deals": 2,
        "effective_extra_deals": 0,
        "effective_max_bots": 0,
        "guardrail_block_reason": None,
        "last_evaluated_at": "2026-03-18 12:00:00",
    }

    async def fail_if_called(*_args, **_kwargs) -> float:
        raise AssertionError("exchange balance should not be fetched")

    async def fake_remaining_reserve(*_args, **_kwargs) -> float:
        return 0.0

    monkeypatch.setattr(
        service.exchange,
        "get_free_balance_for_asset",
        fail_if_called,
    )
    monkeypatch.setattr(
        service,
        "_estimate_remaining_open_trade_reserve",
        fake_remaining_reserve,
    )

    override = await service.get_override(
        _build_config(),
        funds_locked=100.0,
        base_max_bots=3,
        available_quote=1_000.0,
    )

    assert override["green_phase_active"] is True
    assert override["effective_extra_deals"] == 2
    assert override["effective_max_bots"] == 5
