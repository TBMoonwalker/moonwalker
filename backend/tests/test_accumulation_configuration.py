"""Real-SQLite selection, release gating and configuration concurrency checks."""

import asyncio
import json
from unittest.mock import AsyncMock

import model
import pytest
import pytest_asyncio
from service import accumulation_config, accumulation_runtime
from service.accumulation_strategy import build_accumulation_strategy_document
from service.config import Config
from service.config_migrations import canonicalize_trade_mode_rows
from service.trading_maintenance import TradingMaintenanceBarrier
from tortoise import Tortoise


@pytest_asyncio.fixture
async def selection(tmp_path, monkeypatch):
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'selection.sqlite'}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()
    monkeypatch.setattr(
        "service.config.redis_client.publish", AsyncMock(return_value=1)
    )
    barrier = TradingMaintenanceBarrier()
    monkeypatch.setattr(accumulation_config, "trading_maintenance_barrier", barrier)
    monkeypatch.setattr(accumulation_runtime, "ACCUMULATION_RUNTIME_AVAILABLE", True)
    config = Config()
    version = await model.StrategyVersion.create(
        strategy_slug="accumulation_fixture",
        version=1,
        ir_json=json.dumps(build_accumulation_strategy_document()),
        validation_json="{}",
        explanation="test",
    )
    updates = {
        "trade_mode": {"value": "accumulation", "type": "str"},
        "dca": {"value": True, "type": "bool"},
        "signal": {"value": "asap", "type": "str"},
        "symbol_list": {"value": "BTC/USDC", "type": "str"},
        "currency": {"value": "USDC", "type": "str"},
        "market": {"value": "spot", "type": "str"},
        "dry_run": {"value": True, "type": "bool"},
        "accumulation_strategy_version_id": {"value": version.id, "type": "int"},
    }
    yield config, updates, version, barrier
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_release_gate_rejects_selection_atomically(selection, monkeypatch):
    config, updates, *_ = selection
    monkeypatch.setattr(accumulation_runtime, "ACCUMULATION_RUNTIME_AVAILABLE", False)
    with pytest.raises(ValueError, match="unavailable"):
        await config.batch_set(
            {**updates, "timezone": {"value": "Europe/Vienna", "type": "str"}}
        )
    assert not await model.AppConfig.all().exists()
    assert config.get("trade_mode") == "dynamic_dca"
    with pytest.raises(ValueError, match="read-only"):
        await config.set("accumulation_available", {"value": True, "type": "bool"})


@pytest.mark.asyncio
async def test_selection_pin_survives_reload_and_safe_backup_normalization(selection):
    config, updates, version, _ = selection
    await config.batch_set(updates)
    await config.load_all()
    assert config.get("trade_mode") == "accumulation"
    assert config.get("accumulation_strategy_version_id") == version.id
    rows = canonicalize_trade_mode_rows(
        [{"key": "trade_mode", "value": "accumulation", "value_type": "str"}]
    )
    assert rows[0]["value"] == "accumulation"
    with pytest.raises(ValueError, match="Unknown trade mode"):
        canonicalize_trade_mode_rows(
            [{"key": "trade_mode", "value": "unexpected", "value_type": "str"}]
        )


@pytest.mark.asyncio
async def test_dry_run_draft_may_omit_pin_but_live_activation_cannot(selection):
    config, updates, version, _ = selection
    updates.pop("accumulation_strategy_version_id")
    await config.batch_set(updates)
    with pytest.raises(ValueError, match="before live entry"):
        await config.set("dry_run", {"value": False, "type": "bool"})
    assert config.get("dry_run") is True
    await config.set(
        "accumulation_strategy_version_id", {"value": version.id, "type": "int"}
    )
    await config.set("dry_run", {"value": False, "type": "bool"})
    assert config.get("dry_run") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, 1.0, "1", -1, 0])
async def test_pin_requires_exact_positive_integer(selection, value):
    config, *_ = selection
    with pytest.raises(ValueError, match="exact positive integer"):
        await config.set(
            "accumulation_strategy_version_id", {"value": value, "type": "int"}
        )
    assert not await model.AppConfig.all().exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,value,type_name",
    [
        ("signal", "websocket_signal", "str"),
        ("symbol_list", "https://example.test/pairs", "str"),
        ("symbol_list", "BTC/USDT", "str"),
        ("market", "swap", "str"),
        ("autopilot", True, "bool"),
    ],
)
async def test_incompatible_selection_does_not_partially_persist(
    selection, key, value, type_name
):
    config, updates, *_ = selection
    with pytest.raises(ValueError):
        await config.batch_set({**updates, key: {"value": value, "type": type_name}})
    assert not await model.AppConfig.all().exists()


@pytest.mark.asyncio
async def test_incompatible_strategy_pin_is_rejected_before_commit(selection):
    config, updates, *_ = selection
    ordinary = await model.StrategyVersion.create(
        strategy_slug="ordinary",
        version=1,
        ir_json="{}",
        validation_json="{}",
        explanation="test",
    )
    updates["accumulation_strategy_version_id"]["value"] = ordinary.id
    with pytest.raises(ValueError, match="accumulation contract"):
        await config.batch_set(updates)
    assert not await model.AppConfig.all().exists()


@pytest.mark.asyncio
async def test_live_mode_change_requires_pause_and_no_managed_exposure(selection):
    config, updates, *_ = selection
    await config.set("dry_run", {"value": False, "type": "bool"})
    updates["dry_run"]["value"] = False
    with pytest.raises(ValueError, match="Pause Moonwalker"):
        await config.batch_set(updates)
    await config.set("trading_paused", {"value": True, "type": "bool"})
    holding = await model.OpenTrades.create(symbol="BTC/USDC")
    with pytest.raises(ValueError, match="Finish existing"):
        await config.batch_set(updates)
    await holding.delete()
    activation = await model.AccumulationActivation.create(
        symbol="ETH/USDC", account_scope="test", state="paused"
    )
    with pytest.raises(ValueError, match="Finish existing"):
        await config.batch_set(updates)
    activation.state = "stopped"
    await activation.save()
    await config.batch_set(updates)
    assert config.get("trade_mode") == "accumulation"


@pytest.mark.asyncio
async def test_mode_change_drains_orders_without_holding_the_config_lock(selection):
    config, updates, _, barrier = selection
    entered, release = asyncio.Event(), asyncio.Event()

    async def order():
        async with barrier.operation():
            entered.set()
            await release.wait()
            await config.set("timezone", {"value": "Europe/Vienna", "type": "str"})

    operation = asyncio.create_task(order())
    await entered.wait()
    change = asyncio.create_task(config.batch_set(updates))
    await asyncio.sleep(0)
    assert not change.done()
    release.set()
    await asyncio.wait_for(asyncio.gather(operation, change), 5)
    assert config.get("timezone") == "Europe/Vienna"
    assert config.get("trade_mode") == "accumulation"


@pytest.mark.asyncio
async def test_unknown_persisted_mode_never_migrates_into_dynamic_dca(selection):
    from service.config_migrations import (
        TRADE_MODE_MIGRATION_VERSION,
        run_config_migrations,
    )

    await model.AppConfig.create(
        key="trade_mode", value="unknown_mode", value_type="str"
    )
    with pytest.raises(ValueError, match="Unknown trade mode"):
        await run_config_migrations()
    assert (await model.AppConfig.get(key="trade_mode")).value == "unknown_mode"
    assert not await model.ConfigMigration.filter(
        version=TRADE_MODE_MIGRATION_VERSION
    ).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("currency", ["usdc", "UsDc", " USDC "])
async def test_accumulation_setup_accepts_quote_case_from_exchange_selector(
    selection, currency
):
    config, updates, version, _ = selection
    updates["currency"]["value"] = currency
    await config.batch_set(updates)
    assert config.get("trade_mode") == "accumulation"
    assert config.get("accumulation_strategy_version_id") == version.id
