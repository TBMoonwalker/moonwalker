"""Telegram notification coverage for settled accumulation fills."""

import json
from datetime import datetime, timedelta, timezone

import model
import pytest
import pytest_asyncio
from service.accumulation.accounting import persist_accumulation_order
from service.accumulation.fill import AccumulationFill
from service.accumulation.lifecycle import AccumulationLifecycleService
from service.accumulation.trade_notifications import (
    build_accumulation_trade_payload,
    notify_accumulation_trade,
)
from service.lifecycle_mutation import LifecycleMutationCoordinator
from service.trading_maintenance import TradingMaintenanceBarrier
from tortoise import Tortoise

CONFIG = {"exchange": "binance", "dry_run": False, "market": "spot"}


@pytest_asyncio.fixture
async def accounting_db(tmp_path, monkeypatch):
    url = f"sqlite://{tmp_path / 'trade_notifications.sqlite'}"
    await Tortoise.init(db_url=url, modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    coordinator = LifecycleMutationCoordinator(TradingMaintenanceBarrier())
    for module in (
        "accumulation.accounting",
        "accumulation.lifecycle",
        "accumulation.repair",
        "accumulation.account_rebind",
    ):
        monkeypatch.setattr(
            f"service.{module}.lifecycle_mutation_coordinator", coordinator
        )
    yield url
    await Tortoise.close_connections()


async def _buy():
    version = await model.StrategyVersion.create(
        strategy_slug="accumulation",
        version=1,
        ir_json="{}",
        validation_json="{}",
        explanation="fixture",
    )
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC",
        account_scope="account-1",
        state="enabled",
        explicitly_paused=False,
        strategy_version=version,
    )
    opportunity = await model.AccumulationOpportunity.create(
        activation=activation,
        generation=activation.generation,
        strategy_version=version,
        observation_epoch=0,
        signal_close_ms=1000,
        expires_at_ms=int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000
        ),
        signal_price="97",
        signal_atr="2",
        unresolved_slot=activation.id,
    )
    placement = await model.PlacementIntent.create(
        operation_id="buy-1",
        symbol="BTC/USDC",
        exchange_name="binance",
        exchange_order_id="exchange-buy-1",
        side="buy",
        action="buy",
        order_type="market",
        state="accepted",
        reserved_quote=1000,
    )
    await model.AccumulationAttempt.create(opportunity=opportunity, placement=placement)
    return activation, opportunity, placement


def _order(*, filled="10", cost="100", status="closed", fees=None, side="buy"):
    return {
        "id": f"exchange-{side}-1",
        "symbol": "BTC/USDC",
        "side": side,
        "filled": filled,
        "cost": cost,
        "status": status,
        "timestamp": 2000,
        "fees": [{"currency": "USDC", "cost": "0"}] if fees is None else fees,
    }


async def _sell(activation, action="sell_partial", quantity="2"):
    await activation.refresh_from_db()
    payload = {
        "symbol": activation.symbol,
        "operation_id": "manual-1",
        "action": action,
        "expected_revision": activation.revision,
    }
    if action == "sell_partial":
        payload["quantity"] = quantity
    await AccumulationLifecycleService().submit(payload, account_scope="account-1")
    operation = await model.AccumulationLifecycleOperation.get(operation_id="manual-1")
    placement = await model.PlacementIntent.create(
        operation_id="sell-1",
        symbol="BTC/USDC",
        exchange_name="binance",
        exchange_order_id="exchange-sell-1",
        side="sell",
        action="sell",
        order_type="market",
        state="accepted",
        request_json=json.dumps(
            {"accumulation_operation_id": "manual-1", "accumulation_action": action}
        ),
    )
    operation.placement = placement
    await operation.save()
    return placement


def _record_notifications(monkeypatch) -> list:
    calls = []

    class FakeMonitoringService:
        async def notify_trade(self, event_type, payload, config):
            calls.append((event_type, payload, config))

    monkeypatch.setattr(
        "service.accumulation.trade_notifications.MonitoringService",
        lambda: FakeMonitoringService(),
    )
    return calls


def _raise_notifications(monkeypatch) -> None:
    class FailingMonitoringService:
        async def notify_trade(self, event_type, payload, config):
            raise RuntimeError("telegram down")

    monkeypatch.setattr(
        "service.accumulation.trade_notifications.MonitoringService",
        lambda: FailingMonitoringService(),
    )


@pytest.mark.asyncio
async def test_settled_buy_notifies_trade_buy(accounting_db, monkeypatch):
    calls = _record_notifications(monkeypatch)
    await _buy()
    await persist_accumulation_order(
        "buy-1",
        _order(),
        account_scope="account-1",
        exchange_name="binance",
        config=CONFIG,
    )
    assert len(calls) == 1
    event_type, payload, config = calls[0]
    assert event_type == "trade.buy"
    assert config is CONFIG
    assert payload["lifecycle"] == "accumulation"
    assert payload["symbol"] == "BTC/USDC"
    assert payload["side"] == "buy"
    assert payload["timestamp"] == 2000
    assert payload["amount"] == "10"
    assert payload["ordersize"] == "100"
    assert payload["price"] == "10"
    assert payload["fees"] == {"USDC": "0"}
    assert payload["order_id"] == "exchange-buy-1"


@pytest.mark.asyncio
async def test_settled_sell_notifies_trade_sell(accounting_db, monkeypatch):
    calls = _record_notifications(monkeypatch)
    activation, _, _ = await _buy()
    await persist_accumulation_order(
        "buy-1",
        _order(),
        account_scope="account-1",
        exchange_name="binance",
        config=CONFIG,
    )
    placement = await _sell(activation)
    await persist_accumulation_order(
        placement.operation_id,
        _order(side="sell", filled="2", cost="22"),
        account_scope="account-1",
        exchange_name="binance",
        config=CONFIG,
    )
    assert [event for event, _, _ in calls] == ["trade.buy", "trade.sell"]
    _, payload, _ = calls[1]
    assert payload["side"] == "sell"
    assert payload["amount"] == "2"
    assert payload["ordersize"] == "22"
    assert payload["price"] == "11"


@pytest.mark.asyncio
async def test_partial_fill_sends_nothing_until_settled(accounting_db, monkeypatch):
    calls = _record_notifications(monkeypatch)
    await _buy()
    await persist_accumulation_order(
        "buy-1",
        _order(status="open", filled="4", cost="40"),
        account_scope="account-1",
        exchange_name="binance",
        config=CONFIG,
    )
    assert calls == []
    await persist_accumulation_order(
        "buy-1",
        _order(),
        account_scope="account-1",
        exchange_name="binance",
        config=CONFIG,
    )
    assert [event for event, _, _ in calls] == ["trade.buy"]
    _, payload, _ = calls[0]
    assert payload["amount"] == "10"


@pytest.mark.asyncio
async def test_fee_completion_settles_and_notifies_exactly_once(
    accounting_db, monkeypatch
):
    calls = _record_notifications(monkeypatch)
    await _buy()
    first = {
        "id": "exchange-buy-1",
        "symbol": "BTC/USDC",
        "side": "buy",
        "filled": "10",
        "cost": "100",
        "status": "closed",
        "timestamp": 2000,
        "fees": [],
    }
    result = await persist_accumulation_order(
        "buy-1",
        first,
        account_scope="account-1",
        exchange_name="binance",
        config=CONFIG,
    )
    assert result.settled is False
    assert calls == []
    await persist_accumulation_order(
        "buy-1",
        _order(),
        account_scope="account-1",
        exchange_name="binance",
        config=CONFIG,
    )
    assert [event for event, _, _ in calls] == ["trade.buy"]


@pytest.mark.asyncio
async def test_identical_evidence_reread_notifies_once(accounting_db, monkeypatch):
    calls = _record_notifications(monkeypatch)
    await _buy()
    for _ in range(3):
        await persist_accumulation_order(
            "buy-1",
            _order(),
            account_scope="account-1",
            exchange_name="binance",
            config=CONFIG,
        )
    assert [event for event, _, _ in calls] == ["trade.buy"]


@pytest.mark.asyncio
async def test_notification_failure_never_breaks_accounting(accounting_db, monkeypatch):
    _raise_notifications(monkeypatch)
    await _buy()
    result = await persist_accumulation_order(
        "buy-1",
        _order(),
        account_scope="account-1",
        exchange_name="binance",
        config=CONFIG,
    )
    assert result.settled is True
    assert (await model.PlacementIntent.get(operation_id="buy-1")).state == "persisted"


def test_build_payload_computes_average_price_and_zero_fill_guard():
    report = AccumulationFill.from_order(
        {
            "id": "exchange-buy-1",
            "symbol": "BTC/USDC",
            "side": "buy",
            "filled": "3",
            "cost": "100",
            "status": "closed",
            "timestamp": 2000,
            "fees": [{"currency": "USDC", "cost": "0.25"}],
        }
    )
    payload = build_accumulation_trade_payload(report)
    assert float(payload["price"]) == pytest.approx(100 / 3, rel=1e-12)
    assert payload["fees"] == {"USDC": "0.25"}
    zero = AccumulationFill.from_order(
        {
            "id": "exchange-buy-2",
            "symbol": "BTC/USDC",
            "side": "buy",
            "filled": "0",
            "cost": "0",
            "status": "canceled",
            "timestamp": 2000,
            "fees": [],
        }
    )
    assert build_accumulation_trade_payload(zero)["price"] == "0"


@pytest.mark.asyncio
async def test_notify_accumulation_trade_swallows_service_errors(monkeypatch, caplog):
    _raise_notifications(monkeypatch)
    report = AccumulationFill.from_order(
        {
            "id": "exchange-buy-1",
            "symbol": "BTC/USDC",
            "side": "buy",
            "filled": "1",
            "cost": "10",
            "status": "closed",
            "timestamp": 2000,
            "fees": [],
        }
    )
    with caplog.at_level("ERROR", logger="accumulation"):
        await notify_accumulation_trade(report, CONFIG)
    assert "Accumulation trade notification failed" in caplog.text
