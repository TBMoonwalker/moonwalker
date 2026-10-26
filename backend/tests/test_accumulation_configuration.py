"""Real-SQLite selection, release gating and configuration concurrency checks."""

import asyncio
import json
from unittest.mock import AsyncMock

import model
import pytest
import pytest_asyncio
from service.accumulation import config as accumulation_config
from service.accumulation import runtime as accumulation_runtime
from service.accumulation.lifecycle import AccumulationLifecycleService
from service.accumulation.strategy import build_accumulation_strategy_document
from service.config import Config
from service.config_migrations import canonicalize_trade_mode_rows
from service.csv_signal_import import CSVSignalImportService
from service.lifecycle_routing import LifecycleRoute, load_lifecycle_route
from service.orders import Orders
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
        "bo": {"value": 10, "type": "float"},
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


# Value: protects=settled mode handoff preserves history and new DCA ownership;
# fails_when=historical registration permanently blocks DCA; why_new=existing
# mode and routing tests cover each half separately; seam=none;
# no_claim=exchange acceptance (admission and real SQLite only).
@pytest.mark.asyncio
async def test_settled_mode_switch_releases_dca_admission_without_deleting_history(
    selection,
):
    config, updates, *_ = selection
    await config.batch_set(updates)
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC",
        account_scope="test",
        state="stopped",
        observations_initialized=True,
    )
    operation = await model.AccumulationLifecycleOperation.create(
        operation_id="test-stopped-history",
        activation=activation,
        action="empty_stop",
        request_json="{}",
        status="applied",
        previous_state="enabled",
        previous_paused=False,
        result_state="stopped",
        result_revision=1,
    )
    assert (await load_lifecycle_route("BTC/USDC")).route == LifecycleRoute.ACCUMULATION
    await config.set("trade_mode", {"value": "dynamic_dca", "type": "str"})
    with pytest.raises(ValueError, match="Select Accumulation"):
        await AccumulationLifecycleService().submit(
            {
                "symbol": "BTC/USDC",
                "action": "reactivate",
                "operation_id": "test-stale-tab-reactivation",
                "expected_revision": activation.revision,
            },
            account_scope="test",
        )
    assert not await model.AccumulationLifecycleOperation.filter(
        operation_id="test-stale-tab-reactivation"
    ).exists()
    assert await Orders()._legacy_lifecycle_rejection("BTC/USDC", "buy") is None
    await CSVSignalImportService().import_from_csv(
        "date;symbol;price;amount\n18/08/2025 19:32:00;BTC/USDC;100;1\n",
        "USDC",
        1,
    )
    holding = await model.OpenTrades.get(symbol="BTC/USDC")
    assert holding.amount == 1 and holding.cost == 100
    assert await model.Trades.filter(symbol="BTC/USDC", baseorder=True).count() == 1
    assert (await load_lifecycle_route("BTC/USDC")).route == LifecycleRoute.CLASSIC_DCA
    intent = await model.PlacementIntent.create(
        operation_id="test-new-dca-intent",
        exchange_name="test",
        symbol="BTC/USDC",
        action="buy",
        side="buy",
        order_type="market",
        state="prepared",
    )
    # The new DCA order's own intent must remain eligible for legacy recovery.
    assert (await load_lifecycle_route("BTC/USDC")).route == LifecycleRoute.CLASSIC_DCA
    assert await model.AccumulationLifecycleOperation.filter(id=operation.id).exists()
    await activation.refresh_from_db()
    assert activation.state == "stopped" and activation.holding_id is None
    with pytest.raises(ValueError, match="Finish existing"):
        await config.set("trade_mode", {"value": "accumulation", "type": "str"})
    await holding.delete()
    await intent.delete()
    await config.set("trade_mode", {"value": "accumulation", "type": "str"})
    assert (await load_lifecycle_route("BTC/USDC")).route == LifecycleRoute.ACCUMULATION


# Value: protects=unsettled accumulation work prevents mode handoff;
# fails_when=pending commands or opportunity commitments lose their owner;
# why_new=existing switch guard covers placements and holdings only; seam=none;
# no_claim=exchange recovery (real SQLite admission boundary only).
@pytest.mark.asyncio
@pytest.mark.parametrize("pending", ["command", "opportunity", "placement"])
async def test_mode_handoff_rejects_unsettled_stopped_registrations(selection, pending):
    config, updates, version, _ = selection
    await config.batch_set(updates)
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC", account_scope="test", state="stopped"
    )
    if pending in {"command", "placement"}:
        placement = (
            await model.PlacementIntent.create(
                operation_id="test-unresolved-accumulation",
                exchange_name="test",
                symbol="BTC/USDC",
                action="sell",
                side="sell",
                order_type="market",
                state="indeterminate",
            )
            if pending == "placement"
            else None
        )
        await model.AccumulationLifecycleOperation.create(
            operation_id="test-pending-reactivation",
            activation=activation,
            action="reactivate",
            request_json="{}",
            previous_state="stopped",
            previous_paused=True,
            result_state="stopped",
            result_revision=1,
            status="quarantined" if placement else "pending",
            placement=placement,
        )
    else:
        await model.AccumulationOpportunity.create(
            activation=activation,
            generation=activation.generation,
            strategy_version=version,
            observation_epoch=0,
            signal_close_ms=1,
            expires_at_ms=2,
            signal_price="100",
            signal_atr="1",
            unresolved_slot=activation.id,
        )
    guard = await accumulation_config.configuration_mode_guard(config.snapshot())
    assert guard["blocked"] is True
    with pytest.raises(ValueError, match="Finish existing"):
        await config.set("trade_mode", {"value": "dynamic_dca", "type": "str"})
    # A corrupt/direct mode write must not bypass unresolved ownership either.
    await model.AppConfig.filter(key="trade_mode").update(value="dynamic_dca")
    assert (await load_lifecycle_route("BTC/USDC")).route == LifecycleRoute.ACCUMULATION
    with pytest.raises(ValueError, match="managed or reserved"):
        await CSVSignalImportService().import_from_csv(
            "date;symbol;price;amount\n18/08/2025 19:32:00;BTC/USDC;100;1\n",
            "USDC",
            1,
        )
    assert not await model.OpenTrades.all().exists()
    assert not await model.Trades.all().exists()


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dry_run,paused,holdings,registrations,unresolved,expected",
    [
        (
            True,
            False,
            0,
            1,
            False,
            "Before changing trade mode: stop 1 active accumulation registration.",
        ),
        (True, False, 1, 0, False, "Before changing trade mode: close 1 open holding."),
        (
            True,
            False,
            0,
            0,
            True,
            "Before changing trade mode: reconcile unresolved orders.",
        ),
        (False, False, 0, 0, False, "Before changing trade mode: pause live trading."),
        (False, True, 0, 0, False, None),
        (True, False, 0, 0, False, None),
        (
            True,
            False,
            1,
            1,
            True,
            "Before changing trade mode: close 1 open holding; stop 1 active accumulation registration; reconcile unresolved orders.",
        ),
    ],
)
async def test_mode_switch_message_lists_only_current_blockers(
    selection, dry_run, paused, holdings, registrations, unresolved, expected
):
    for index in range(holdings):
        await model.OpenTrades.create(symbol=f"HOLD{index}/USDC")
    for index in range(registrations):
        await model.AccumulationActivation.create(
            symbol=f"REG{index}/USDC", account_scope="demo-fixture", state="validating"
        )
    if unresolved:
        await model.PlacementIntent.create(
            operation_id="guard-order",
            exchange_name="binance",
            symbol="BTC/USDC",
            action="buy",
            side="buy",
            order_type="limit",
            state="indeterminate",
        )
    guard = await accumulation_config.configuration_mode_guard(
        {"dry_run": dry_run, "trading_paused": paused, "trade_mode": "accumulation"}
    )
    assert guard["blocked"] is (expected is not None)
    assert guard["can_switch"] is (expected is None)
    assert guard["message"] == expected
    if dry_run:
        assert "live" not in (guard["message"] or "")
