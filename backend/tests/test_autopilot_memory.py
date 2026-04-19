import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import model
import pytest
from controller import autopilot_memory as autopilot_memory_controller
from litestar import Litestar
from litestar.testing import TestClient
from service.autopilot_memory import AutopilotMemoryService, SymbolMemorySnapshot
from tortoise import Tortoise


def _utc_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _config(**overrides):
    payload = {
        "autopilot": True,
        "tp": 1.5,
        "bo": 100.0,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_autopilot_memory_refresh_persists_mixed_format_warmup_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.now(timezone.utc)
    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        profit=1.0,
        profit_percent=1.4,
        open_date=_utc_iso(now - timedelta(hours=2)),
        close_date=_utc_iso(now - timedelta(hours=1)),
        duration="1:00:00",
    )
    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        profit=1.1,
        profit_percent=1.5,
        open_date="2026-04-09 10:00:00.000000",
        close_date="2026-04-09 11:30:00.000000",
        duration="1:30:00.000000",
    )
    await model.ClosedTrades.create(
        symbol="SOL/USDT",
        profit=-0.5,
        profit_percent=-1.1,
        open_date=_utc_iso(now - timedelta(hours=6)),
        close_date=_utc_iso(now - timedelta(hours=1, minutes=30)),
        duration="4:30:00",
    )

    service = AutopilotMemoryService()
    service.on_config_change(_config())
    await service.refresh_state()

    payload = service.build_read_model()
    persisted_state = await model.AutopilotMemoryState.get(id=service.STATE_ROW_ID)
    snapshots = await model.AutopilotSymbolMemory.all().order_by("symbol")
    events = await model.AutopilotMemoryEvent.all().order_by("-created_at")

    assert payload["status"] == "warming_up"
    assert payload["warmup"]["current_closes"] == 3
    assert payload["featured"] is not None
    assert payload["featured"]["symbol"] == "BTC/USDT"
    assert persisted_state.status == "warming_up"
    assert len(snapshots) == 2
    assert snapshots[0].weighted_close_hours > 0
    assert any(event.event_type == "memory_warming_up" for event in events)

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_autopilot_memory_fresh_snapshot_applies_adaptive_tp(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    now = datetime.now(timezone.utc)
    for index in range(12):
        await model.ClosedTrades.create(
            symbol="BTC/USDT",
            profit=1.0,
            profit_percent=1.8,
            open_date=_utc_iso(now - timedelta(hours=index + 2)),
            close_date=_utc_iso(now - timedelta(hours=index + 1)),
            duration="1:00:00",
        )
    for index in range(10):
        await model.ClosedTrades.create(
            symbol="SOL/USDT",
            profit=-0.7,
            profit_percent=-1.2,
            open_date=_utc_iso(now - timedelta(hours=index + 30)),
            close_date=_utc_iso(now - timedelta(hours=index + 24)),
            duration="6:00:00",
        )

    service = AutopilotMemoryService()
    service.on_config_change(_config())
    await service.refresh_state()

    payload = service.build_read_model()
    adaptive_policy = service.resolve_symbol_policy(
        "BTC/USDT",
        enabled=True,
        baseline_take_profit=1.5,
        base_order_amount=100.0,
        entry_sizing_enabled=True,
    )
    baseline_policy = service.resolve_symbol_policy(
        "SOL/USDT",
        enabled=True,
        baseline_take_profit=1.5,
        base_order_amount=100.0,
        entry_sizing_enabled=True,
    )

    assert payload["status"] == "fresh"
    assert adaptive_policy["apply_tp"] is True
    assert adaptive_policy["take_profit"] > 1.5
    assert adaptive_policy["apply_entry_size"] is True
    assert adaptive_policy["entry_order_size"] > 100.0
    assert baseline_policy["take_profit"] <= 1.5
    assert baseline_policy["apply_entry_size"] is True
    assert baseline_policy["entry_order_size"] < 100.0

    await Tortoise.close_connections()


def test_autopilot_memory_entry_sizing_stays_on_baseline_when_disabled() -> None:
    service = AutopilotMemoryService()
    service._state = {
        **service._build_default_state(),
        "status": "fresh",
        "enabled": True,
        "last_success_at": datetime.now(timezone.utc),
        "last_updated_at": datetime.now(timezone.utc),
    }
    service._snapshot_map = {
        "BTC/USDT": SymbolMemorySnapshot(
            symbol="BTC/USDT",
            trust_score=72.0,
            trust_direction="favored",
            confidence_bucket="confident",
            confidence_progress=1.0,
            sample_size=12,
            profitable_closes=10,
            loss_count=2,
            slow_close_count=0,
            weighted_profit_percent=1.1,
            weighted_close_hours=1.2,
            tp_delta_ratio=0.9,
            suggested_base_order=115.0,
            primary_reason_code="quick_profitable_closes",
            primary_reason_value=10,
            secondary_reason_code=None,
            secondary_reason_value=None,
            last_closed_at=datetime.now(timezone.utc),
        )
    }

    policy = service.resolve_symbol_policy(
        "BTC/USDT",
        enabled=True,
        baseline_take_profit=1.5,
        base_order_amount=100.0,
        entry_sizing_enabled=False,
    )

    assert policy["apply_tp"] is True
    assert policy["apply_entry_size"] is False
    assert policy["entry_order_size"] == 100.0
    assert policy["suggested_base_order"] == 115.0
    assert policy["entry_reason_code"] == "entry_sizing_disabled"


def test_autopilot_memory_fails_open_when_snapshot_is_stale() -> None:
    service = AutopilotMemoryService()
    service._state = {
        **service._build_default_state(),
        "status": "fresh",
        "enabled": True,
        "last_success_at": datetime.now(timezone.utc) - timedelta(days=1),
        "last_updated_at": datetime.now(timezone.utc) - timedelta(days=1),
    }
    service._snapshot_map = {
        "BTC/USDT": SymbolMemorySnapshot(
            symbol="BTC/USDT",
            trust_score=72.0,
            trust_direction="favored",
            confidence_bucket="confident",
            confidence_progress=1.0,
            sample_size=12,
            profitable_closes=10,
            loss_count=2,
            slow_close_count=0,
            weighted_profit_percent=1.1,
            weighted_close_hours=1.2,
            tp_delta_ratio=0.9,
            suggested_base_order=115.0,
            primary_reason_code="quick_profitable_closes",
            primary_reason_value=10,
            secondary_reason_code=None,
            secondary_reason_value=None,
            last_closed_at=datetime.now(timezone.utc),
        )
    }

    policy = service.resolve_symbol_policy(
        "BTC/USDT",
        enabled=True,
        baseline_take_profit=1.5,
        base_order_amount=100.0,
        entry_sizing_enabled=True,
    )

    assert policy["apply_tp"] is False
    assert policy["take_profit"] == 1.5
    assert policy["memory_status"] == "stale"
    assert policy["apply_entry_size"] is False
    assert policy["entry_order_size"] == 100.0


def test_autopilot_memory_marks_warming_entry_sizing_as_baseline() -> None:
    service = AutopilotMemoryService()
    service._state = {
        **service._build_default_state(),
        "status": "warming_up",
        "enabled": True,
        "current_closes": 5,
        "required_closes": 20,
        "last_updated_at": datetime.now(timezone.utc),
        "last_success_at": datetime.now(timezone.utc),
    }

    policy = service.resolve_symbol_policy(
        "BTC/USDT",
        enabled=True,
        baseline_take_profit=1.5,
        base_order_amount=100.0,
        entry_sizing_enabled=True,
    )

    assert policy["apply_tp"] is False
    assert policy["apply_entry_size"] is False
    assert policy["entry_order_size"] == 100.0
    assert policy["entry_reason_code"] == "memory_warming_up"


def test_autopilot_memory_builds_admission_profiles_from_public_view() -> None:
    service = AutopilotMemoryService()
    service._state = {
        **service._build_default_state(),
        "status": "fresh",
        "enabled": True,
        "last_success_at": datetime.now(timezone.utc),
        "last_updated_at": datetime.now(timezone.utc),
    }
    service._snapshot_map = {
        "BTC/USDT": SymbolMemorySnapshot(
            symbol="BTC/USDT",
            trust_score=72.0,
            trust_direction="favored",
            confidence_bucket="confident",
            confidence_progress=1.0,
            sample_size=12,
            profitable_closes=10,
            loss_count=2,
            slow_close_count=0,
            weighted_profit_percent=1.1,
            weighted_close_hours=1.2,
            tp_delta_ratio=0.9,
            suggested_base_order=115.0,
            primary_reason_code="quick_profitable_closes",
            primary_reason_value=10,
            secondary_reason_code=None,
            secondary_reason_value=None,
            last_closed_at=datetime.now(timezone.utc),
        )
    }

    profiles = service.build_admission_profiles(["BTC/USDT", "ETH/USDT"], enabled=True)

    assert profiles["BTC/USDT"].uses_trust_ranking is True
    assert profiles["BTC/USDT"].reason_code == "quick_profitable_closes"
    assert profiles["ETH/USDT"].memory_status == "fresh"
    assert profiles["ETH/USDT"].uses_trust_ranking is False
    assert profiles["ETH/USDT"].reason_code == "snapshot_missing"


def test_autopilot_memory_http_endpoint_returns_persisted_read_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "status": "fresh",
        "enabled": True,
        "stale": False,
        "stale_reason": None,
        "baseline_mode_active": False,
        "updated_at": "2026-04-09T17:56:03Z",
        "last_success_at": "2026-04-09T17:56:03Z",
        "warmup": {
            "current_closes": 20,
            "required_closes": 20,
            "progress_percent": 100,
        },
        "featured": {"symbol": "BTC/USDT"},
        "portfolio_effect": {},
        "trust_board": {"favored": [], "cooling": []},
        "events": [],
    }

    async def fake_instance():
        return SimpleNamespace(build_read_model=lambda: payload)

    monkeypatch.setattr(
        autopilot_memory_controller.AutopilotMemoryService,
        "instance",
        fake_instance,
    )

    app = Litestar(route_handlers=autopilot_memory_controller.route_handlers)
    with TestClient(app=app) as client:
        response = client.get("/autopilot/memory")

    assert response.status_code == 200
    assert response.json()["featured"]["symbol"] == "BTC/USDT"
