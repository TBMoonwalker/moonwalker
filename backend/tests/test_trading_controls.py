import os

import model
import pytest
from service.trading_controls import TradingControlsService
from tortoise import Tortoise


class _FakeOrders:
    def __init__(self, *, cancel_result: bool) -> None:
        self.cancel_result = cancel_result
        self.cancel_calls: list[tuple[str, dict[str, object]]] = []

    async def cancel_tp_limit_order_prelocked(
        self,
        symbol: str,
        config: dict[str, object],
    ) -> bool:
        from service.lifecycle_mutation import lifecycle_mutation_coordinator

        lifecycle_mutation_coordinator.assert_prelocked(symbol)
        self.cancel_calls.append((symbol, dict(config)))
        if not self.cancel_result:
            return False
        await model.OpenTrades.filter(symbol=symbol).update(
            tp_limit_order_id=None,
            tp_limit_order_price=None,
            tp_limit_order_amount=None,
            tp_limit_order_armed_at=None,
        )
        return True


@pytest.mark.asyncio
async def test_pause_and_resume_classic_mission_are_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "pause-classic.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.OpenTrades.create(
        symbol="BTC/USDT",
        amount=1.0,
        cost=100.0,
        current_price=100.0,
        tp_price=110.0,
        avg_price=100.0,
        open_date="2026-05-14T08:00:00+00:00",
        tp_limit_order_id="tp-limit-1",
        tp_limit_order_price=110.0,
        tp_limit_order_amount=1.0,
        tp_limit_order_armed_at="2026-05-14T08:05:00+00:00",
    )

    controls = TradingControlsService()
    fake_orders = _FakeOrders(cancel_result=True)
    monkeypatch.setattr(controls, "_get_orders", lambda: _async_result(fake_orders))

    paused = await controls.pause_mission("BTC/USDT", {"exchange": "binance"})
    assert paused.status == "paused"
    assert paused.automation_paused is True
    assert fake_orders.cancel_calls == [("BTC/USDT", {"exchange": "binance"})]

    open_trade = await model.OpenTrades.get(symbol="BTC/USDT")
    assert open_trade.automation_paused is True
    assert open_trade.automation_paused_at is not None
    assert open_trade.tp_limit_order_id is None

    already_paused = await controls.pause_mission("BTC/USDT", {"exchange": "binance"})
    assert already_paused.status == "already_paused"

    resumed = await controls.resume_mission("BTC/USDT")
    assert resumed.status == "resumed"
    assert resumed.automation_paused is False

    open_trade = await model.OpenTrades.get(symbol="BTC/USDT")
    assert open_trade.automation_paused is False
    assert open_trade.automation_paused_at is None

    already_resumed = await controls.resume_mission("BTC/USDT")
    assert already_resumed.status == "already_resumed"
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_pause_mission_reports_tp_cancel_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "pause-failed.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.OpenTrades.create(
        symbol="SOL/USDT",
        amount=2.0,
        cost=120.0,
        current_price=60.0,
        tp_price=66.0,
        avg_price=60.0,
        open_date="2026-05-14T08:00:00+00:00",
        tp_limit_order_id="tp-limit-9",
    )

    controls = TradingControlsService()
    fake_orders = _FakeOrders(cancel_result=False)
    monkeypatch.setattr(controls, "_get_orders", lambda: _async_result(fake_orders))

    result = await controls.pause_mission("SOL/USDT", {})

    assert result.status == "tp_cancel_failed"
    open_trade = await model.OpenTrades.get(symbol="SOL/USDT")
    assert open_trade.automation_paused is False
    assert open_trade.tp_limit_order_id == "tp-limit-9"
    await Tortoise.close_connections()


def _async_result(value):
    async def _inner():
        return value

    return _inner()
