"""Tests for exchange limit order manager."""

import pytest
from service.exchange_limit_order_manager import ExchangeLimitOrderManager


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

    def amount_to_precision(self, _symbol: str, amount: float) -> str:
        return f"{amount:.3f}"

    def price_to_precision(self, _symbol: str, price: float) -> str:
        return f"{price:.2f}"

    async def create_order(
        self,
        _symbol: str,
        _ordertype: str,
        _side: str,
        _amount: str,
        _price: str,
        _params: dict[str, object],
    ) -> dict[str, object]:
        self.create_order_calls += 1
        return {"id": "limit-1"}


@pytest.mark.asyncio
async def test_create_spot_limit_sell_returns_market_fallback_when_below_notional() -> (
    None
):
    exchange = _DummyExchange()
    manager = ExchangeLimitOrderManager(_DummyLogger(), get_exchange=lambda: exchange)

    async def fake_ensure_exchange(_config: dict[str, object]) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_resolve_sell_amount(
        _symbol: str,
        _requested_amount: float,
    ) -> tuple[str, float]:
        return "BTC/USDT", 0.01

    async def fake_get_price_for_symbol(_symbol: str) -> str:
        return "100000.0"

    async def fake_handle_limit_sell_fill(
        _sell_order: dict[str, object],
        _resolved_symbol: str,
        _config: dict[str, object],
        _original_order: dict[str, object],
    ) -> dict[str, object] | None:
        raise AssertionError("fill handling should not run")

    status = await manager.create_spot_limit_sell(
        order={"symbol": "BTC/USDT", "total_amount": 0.01},
        config={},
        ensure_exchange=fake_ensure_exchange,
        ensure_markets_loaded=fake_ensure_markets_loaded,
        resolve_symbol=lambda symbol: symbol,
        resolve_sell_amount=fake_resolve_sell_amount,
        is_notional_below_minimum=lambda _symbol, _amount, _price: (True, 10.0, 5.0),
        get_price_for_symbol=fake_get_price_for_symbol,
        handle_limit_sell_fill=fake_handle_limit_sell_fill,
    )

    assert status == {
        "requires_market_fallback": True,
        "limit_cancel_confirmed": True,
        "symbol": "BTC/USDT",
        "remaining_amount": 0.01,
        "partial_filled_amount": 0.0,
        "partial_avg_price": 0.0,
    }
    assert exchange.create_order_calls == 0


@pytest.mark.asyncio
async def test_create_spot_limit_sell_places_order_and_delegates_fill_handling() -> (
    None
):
    exchange = _DummyExchange()
    manager = ExchangeLimitOrderManager(_DummyLogger(), get_exchange=lambda: exchange)
    handled: dict[str, object] = {}

    async def fake_ensure_exchange(_config: dict[str, object]) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_resolve_sell_amount(
        _symbol: str,
        _requested_amount: float,
    ) -> tuple[str, float]:
        return "ETH/USDT", 1.25

    async def fake_get_price_for_symbol(_symbol: str) -> str:
        return "2500.0"

    async def fake_handle_limit_sell_fill(
        sell_order: dict[str, object],
        resolved_symbol: str,
        _config: dict[str, object],
        _original_order: dict[str, object],
    ) -> dict[str, object] | None:
        handled["sell_order"] = sell_order
        handled["resolved_symbol"] = resolved_symbol
        return {"type": "sold_check", "symbol": resolved_symbol}

    status = await manager.create_spot_limit_sell(
        order={"symbol": "ETH/USDT", "total_amount": 1.25, "current_price": 2500.0},
        config={},
        ensure_exchange=fake_ensure_exchange,
        ensure_markets_loaded=fake_ensure_markets_loaded,
        resolve_symbol=lambda symbol: symbol,
        resolve_sell_amount=fake_resolve_sell_amount,
        is_notional_below_minimum=lambda _symbol, _amount, _price: (False, None, 0.0),
        get_price_for_symbol=fake_get_price_for_symbol,
        handle_limit_sell_fill=fake_handle_limit_sell_fill,
    )

    assert status == {"type": "sold_check", "symbol": "ETH/USDT"}
    assert exchange.create_order_calls == 1
    assert handled["resolved_symbol"] == "ETH/USDT"
    assert handled["sell_order"] == {
        "symbol": "ETH/USDT",
        "total_amount": 1.25,
        "current_price": 2500.0,
        "id": "limit-1",
    }
