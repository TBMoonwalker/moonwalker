import types

import model
import pytest
from service.autopilot import Autopilot
from service.autopilot_runtime import AutopilotRuntimeState


@pytest.mark.asyncio
async def test_autopilot_high_threshold_triggers_db_write(monkeypatch) -> None:
    created_modes = []

    async def fake_create(**kwargs) -> None:
        created_modes.append(kwargs.get("mode"))

    monkeypatch.setattr(model, "Autopilot", types.SimpleNamespace(create=fake_create))

    config = {
        "autopilot": True,
        "capital_max_fund": 100,
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

    autopilot = Autopilot(runtime_state=AutopilotRuntimeState())
    autopilot.green_phase_service = types.SimpleNamespace(
        get_override=_green_override(
            green_phase_detected=True,
            green_phase_active=True,
            effective_extra_deals=2,
            effective_max_bots=7,
            phase_strength=2.4,
            ramp_ready=True,
            guardrail_block_reason=None,
        )
    )
    autopilot.memory_service = _memory_summary()
    settings = await autopilot.calculate_trading_settings(90, config)

    assert settings["mode"] == "high"
    assert settings["mad"] == 7
    assert settings["tp"] == 1.2
    assert settings["sl"] == 2.5
    assert settings["sl_timeout"] == 7
    assert settings["green_phase_active"] is True
    assert settings["green_phase_extra_deals"] == 2
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
        "capital_max_fund": 100,
        "autopilot_high_threshold": 80,
        "autopilot_medium_threshold": 50,
        "max_bots": 4,
    }

    autopilot = Autopilot(runtime_state=AutopilotRuntimeState())
    autopilot.green_phase_service = types.SimpleNamespace(
        get_override=_green_override(
            green_phase_detected=True,
            green_phase_active=True,
            effective_extra_deals=1,
            effective_max_bots=5,
            phase_strength=1.8,
            ramp_ready=True,
            guardrail_block_reason=None,
        )
    )
    autopilot.memory_service = _memory_summary()
    settings = await autopilot.calculate_trading_settings(10, config)
    runtime_state = await autopilot.resolve_runtime_state(10, config)

    assert settings == {}
    assert runtime_state["mode"] == "low"
    assert runtime_state["effective_max_bots"] == 5
    assert runtime_state["green_phase_active"] is True
    assert runtime_state["green_phase_extra_deals"] == 1
    assert created_modes == ["low"]


@pytest.mark.asyncio
async def test_autopilot_disabled_persists_none_mode(monkeypatch) -> None:
    created_modes = []

    async def fake_create(**kwargs) -> None:
        created_modes.append(kwargs.get("mode"))

    monkeypatch.setattr(model, "Autopilot", types.SimpleNamespace(create=fake_create))

    autopilot = Autopilot(runtime_state=AutopilotRuntimeState())
    autopilot.memory_service = _memory_summary(status="empty", current_closes=0)
    settings = await autopilot.calculate_trading_settings(10, {"autopilot": False})
    runtime_state = await autopilot.resolve_runtime_state(10, {"autopilot": False})

    assert settings == {}
    assert runtime_state["mode"] == "none"
    assert created_modes == ["none"]


@pytest.mark.asyncio
async def test_autopilot_passes_available_quote_override_to_green_phase(
    monkeypatch,
) -> None:
    created_modes = []
    captured: dict[str, object] = {}

    async def fake_create(**kwargs) -> None:
        created_modes.append(kwargs.get("mode"))

    async def fake_get_override(*_args, **kwargs):
        captured["available_quote"] = kwargs.get("available_quote")
        return {
            "green_phase_detected": False,
            "green_phase_active": False,
            "effective_extra_deals": 0,
            "effective_max_bots": 4,
            "phase_strength": 0.0,
            "ramp_ready": False,
            "guardrail_block_reason": None,
        }

    monkeypatch.setattr(model, "Autopilot", types.SimpleNamespace(create=fake_create))

    autopilot = Autopilot(runtime_state=AutopilotRuntimeState())
    autopilot.green_phase_service = types.SimpleNamespace(
        get_override=fake_get_override
    )
    autopilot.memory_service = _memory_summary()
    config = {
        "autopilot": True,
        "capital_max_fund": 100,
        "autopilot_high_threshold": 80,
        "autopilot_medium_threshold": 50,
        "max_bots": 4,
    }

    runtime_state = await autopilot.resolve_runtime_state(
        10,
        config,
        available_quote=321.5,
    )

    assert runtime_state["effective_max_bots"] == 4
    assert captured["available_quote"] == 321.5
    assert created_modes == ["low"]


@pytest.mark.asyncio
async def test_autopilot_runtime_state_is_instance_injectable(monkeypatch) -> None:
    created_modes = []

    async def fake_create(**kwargs) -> None:
        created_modes.append(kwargs.get("mode"))

    monkeypatch.setattr(model, "Autopilot", types.SimpleNamespace(create=fake_create))

    shared_runtime_state = AutopilotRuntimeState()
    first = Autopilot(runtime_state=shared_runtime_state)
    second = Autopilot(runtime_state=shared_runtime_state)
    first.green_phase_service = types.SimpleNamespace(get_override=_green_override())
    second.green_phase_service = types.SimpleNamespace(get_override=_green_override())
    first.memory_service = _memory_summary()
    second.memory_service = _memory_summary()
    config = {
        "autopilot": True,
        "capital_max_fund": 100,
        "autopilot_high_threshold": 80,
        "autopilot_medium_threshold": 50,
        "max_bots": 4,
    }

    await first.resolve_runtime_state(10, config)
    await second.resolve_runtime_state(10, config)

    assert created_modes == ["low"]


def test_autopilot_init_does_not_reset_runtime_state() -> None:
    runtime_state = AutopilotRuntimeState(
        last_threshold_percent=42.0,
        last_mode="medium",
    )

    Autopilot(runtime_state=runtime_state)

    assert runtime_state.last_threshold_percent == 42.0
    assert runtime_state.last_mode == "medium"


@pytest.mark.asyncio
async def test_autopilot_resolve_trading_policy_exposes_entry_sizing_fields(
    monkeypatch,
) -> None:
    created_modes = []

    async def fake_create(**kwargs) -> None:
        created_modes.append(kwargs.get("mode"))

    monkeypatch.setattr(model, "Autopilot", types.SimpleNamespace(create=fake_create))

    autopilot = Autopilot(runtime_state=AutopilotRuntimeState())
    autopilot.green_phase_service = types.SimpleNamespace(
        get_override=_green_override(
            green_phase_detected=False,
            green_phase_active=False,
            effective_extra_deals=0,
            effective_max_bots=4,
            phase_strength=0.0,
            ramp_ready=False,
            guardrail_block_reason=None,
        )
    )
    autopilot.memory_service = types.SimpleNamespace(
        get_runtime_summary=lambda: _memory_summary().get_runtime_summary(),
        resolve_symbol_policy=lambda *_args, **_kwargs: {
            "apply_tp": True,
            "take_profit": 1.4,
            "suggested_base_order": 115.0,
            "apply_entry_size": True,
            "entry_order_size": 115.0,
            "entry_reason_code": "quick_profitable_closes",
            "memory_status": "fresh",
            "reason_code": "quick_profitable_closes",
            "trust_score": 72.0,
            "trust_direction": "favored",
        },
    )

    policy = await autopilot.resolve_trading_policy(
        "BTC/USDT",
        10.0,
        {
            "autopilot": True,
            "capital_max_fund": 100,
            "autopilot_high_threshold": 80,
            "autopilot_medium_threshold": 50,
            "max_bots": 4,
            "tp": 1.2,
            "bo": 100.0,
            "autopilot_symbol_entry_sizing_enabled": True,
        },
    )

    assert policy.adaptive_tp_applied is True
    assert policy.adaptive_trust_direction == "favored"
    assert policy.adaptive_entry_size_applied is True
    assert policy.adaptive_entry_reason_code == "quick_profitable_closes"
    assert policy.baseline_base_order == 100.0
    assert policy.entry_order_size == 115.0
    assert created_modes == ["low"]


def _green_override(**values):
    async def _inner(*_args, **_kwargs):
        return values

    return _inner


def _memory_summary(**overrides):
    payload = {
        "status": "fresh",
        "stale": False,
        "stale_reason": None,
        "current_closes": 24,
        "required_closes": 20,
        "featured_symbol": "BTC/USDT",
        "featured_direction": "favored",
        "last_updated_at": "2026-04-09T17:56:03Z",
        "last_success_at": "2026-04-09T17:56:03Z",
    }
    payload.update(overrides)
    return types.SimpleNamespace(
        get_runtime_summary=lambda: payload,
        resolve_symbol_policy=lambda *_args, **_kwargs: {
            "apply_tp": False,
            "take_profit": 1.2,
            "suggested_base_order": 50.0,
            "apply_entry_size": False,
            "entry_order_size": 50.0,
            "entry_reason_code": "entry_sizing_disabled",
            "memory_status": payload["status"],
            "reason_code": payload["stale_reason"],
            "trust_score": None,
            "trust_direction": "neutral",
        },
    )
