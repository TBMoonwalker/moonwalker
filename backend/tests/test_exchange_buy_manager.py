"""Tests for exchange buy manager."""

import pytest
from service.exchange_buy_manager import ExchangeBuyManager
from service.exchange_contexts import BuyFinalizationContext


class _DummyLogger:
    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass

    def error(self, *_args, **_kwargs) -> None:
        pass

    def debug(self, *_args, **_kwargs) -> None:
        pass


class _DummyExchange:
    def __init__(self) -> None:
        self.create_order_calls = 0
        self.fetch_trading_fee_calls = 0

    async def create_order(
        self,
        symbol: str,
        ordertype: str,
        side: str,
        amount: str,
        price: str,
        _params: dict[str, object],
    ) -> dict[str, object]:
        self.create_order_calls += 1
        return {
            "id": "buy-1",
            "symbol": symbol,
            "type": ordertype,
            "side": side,
            "amount": amount,
            "price": price,
        }

    async def fetch_trading_fee(self, symbol: str) -> dict[str, object]:
        self.fetch_trading_fee_calls += 1
        return {"symbol": symbol, "taker": 0.001}


@pytest.mark.asyncio
async def test_execute_market_buy_places_order() -> None:
    exchange = _DummyExchange()
    manager = ExchangeBuyManager(_DummyLogger(), get_exchange=lambda: exchange)

    order = await manager.execute_market_buy(
        {
            "symbol": "BTC/USDT",
            "ordertype": "market",
            "side": "buy",
            "amount": "0.01",
            "price": "100000.0",
        }
    )

    assert order is not None
    assert order["id"] == "buy-1"
    assert exchange.create_order_calls == 1


@pytest.mark.asyncio
async def test_finalize_market_buy_applies_demo_fee_and_base_fee_deduction() -> None:
    exchange = _DummyExchange()
    manager = ExchangeBuyManager(_DummyLogger(), get_exchange=lambda: exchange)

    async def fake_parse_order_status(
        _order: dict[str, object],
    ) -> dict[str, object]:
        return {
            "symbol": "BTC/USDT",
            "amount": 2.0,
            "base_fee": 0.1,
        }

    async def fake_get_precision_for_symbol(_symbol: str) -> int:
        return 6

    result = await manager.finalize_market_buy(
        order={"symbol": "BTC/USDT", "id": "buy-1"},
        config={"dry_run": True, "fee_deduction": False},
        context=BuyFinalizationContext(
            parse_order_status=fake_parse_order_status,
            get_precision_for_symbol=fake_get_precision_for_symbol,
            resolve_symbol=lambda symbol: symbol,
            get_demo_taker_fee_for_symbol=lambda _symbol: 0.0025,
        ),
    )

    assert result is not None
    assert result["precision"] == 6
    assert result["fees"] == 0.0025
    assert result["amount_fee"] == 0.1
    assert result["amount"] == pytest.approx(1.9)


@pytest.mark.asyncio
async def test_finalize_market_buy_uses_live_fee_when_not_dry_run() -> None:
    exchange = _DummyExchange()
    manager = ExchangeBuyManager(_DummyLogger(), get_exchange=lambda: exchange)

    async def fake_parse_order_status(
        _order: dict[str, object],
    ) -> dict[str, object]:
        return {
            "symbol": "ETH/USDT",
            "amount": 3.0,
            "base_fee": 0.25,
        }

    async def fake_get_precision_for_symbol(_symbol: str) -> int:
        return 4

    result = await manager.finalize_market_buy(
        order={"symbol": "ETH/USDT", "id": "buy-2"},
        config={"dry_run": False, "fee_deduction": True},
        context=BuyFinalizationContext(
            parse_order_status=fake_parse_order_status,
            get_precision_for_symbol=fake_get_precision_for_symbol,
            resolve_symbol=lambda symbol: symbol,
            get_demo_taker_fee_for_symbol=lambda _symbol: 0.0,
        ),
    )

    assert result is not None
    assert result["precision"] == 4
    assert result["fees"] == 0.001
    assert result["amount_fee"] == 0.0
    assert result["amount"] == 3.0
    assert exchange.fetch_trading_fee_calls == 1
