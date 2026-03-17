import types

import model
import pytest
from service.autopilot import Autopilot


@pytest.mark.asyncio
async def test_autopilot_high_threshold_triggers_db_write(monkeypatch) -> None:
    created_modes = []

    async def fake_create(**kwargs) -> None:
        created_modes.append(kwargs.get("mode"))

    monkeypatch.setattr(model, "Autopilot", types.SimpleNamespace(create=fake_create))

    config = {
        "autopilot": True,
        "autopilot_max_fund": 100,
        "autopilot_high_threshold": 80,
        "autopilot_high_mad": 5,
        "autopilot_high_tp": 1.2,
        "autopilot_high_sl": 2.5,
        "autopilot_high_sl_timeout": 7,
        "autopilot_medium_threshold": 50,
        "autopilot_medium_mad": 3,
        "autopilot_medium_tp": 1.0,
        "autopilot_medium_sl": 2.0,
        "autopilot_medium_sl_timeout": 10,
    }

    autopilot = Autopilot()
    settings = await autopilot.calculate_trading_settings(90, config)

    assert settings["mode"] == "high"
    assert settings["mad"] == 5
    assert settings["tp"] == 1.2
    assert settings["sl"] == 2.5
    assert settings["sl_timeout"] == 7
    assert created_modes == ["high"]


@pytest.mark.asyncio
async def test_autopilot_enabled_below_threshold_persists_low_mode(
    monkeypatch,
) -> None:
    created_modes = []

    async def fake_create(**kwargs) -> None:
        created_modes.append(kwargs.get("mode"))

    monkeypatch.setattr(model, "Autopilot", types.SimpleNamespace(create=fake_create))

    config = {
        "autopilot": True,
        "autopilot_max_fund": 100,
        "autopilot_high_threshold": 80,
        "autopilot_medium_threshold": 50,
    }

    autopilot = Autopilot()
    settings = await autopilot.calculate_trading_settings(10, config)

    assert settings == {}
    assert created_modes == ["low"]


@pytest.mark.asyncio
async def test_autopilot_disabled_persists_none_mode(monkeypatch) -> None:
    created_modes = []

    async def fake_create(**kwargs) -> None:
        created_modes.append(kwargs.get("mode"))

    monkeypatch.setattr(model, "Autopilot", types.SimpleNamespace(create=fake_create))

    autopilot = Autopilot()
    settings = await autopilot.calculate_trading_settings(10, {"autopilot": False})

    assert settings == {}
    assert created_modes == ["none"]
