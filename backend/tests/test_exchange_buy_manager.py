"""Tests for exchange buy manager."""

import ccxt.async_support as ccxt
import pytest
from service.exchange_buy_manager import ExchangeBuyManager
from service.exchange_capabilities import ExchangePostSubmissionFailure
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
        self.cancel_order_calls = 0
        self.last_create_order: dict[str, object] | None = None
        self.next_filled: float | str | None = None
        self.next_status = "closed"
        self.omit_filled = False

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
        self.last_create_order = {
            "symbol": symbol,
            "ordertype": ordertype,
            "side": side,
            "amount": amount,
            "price": price,
            "params": _params,
        }
        result: dict[str, object] = {
            "id": "buy-1",
            "symbol": symbol,
            "type": ordertype,
            "side": side,
            "amount": amount,
            "price": price,
            "status": self.next_status,
        }
        if not self.omit_filled:
            result["filled"] = (
                float(amount) if self.next_filled is None else self.next_filled
            )
        return result

    def price_to_precision(self, _symbol: str, price: float) -> str:
        return f"{price:.5f}"

    async def cancel_order(self, _order_id: str, _symbol: str) -> None:
        self.cancel_order_calls += 1

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
async def test_capped_recovery_buy_uses_ioc_limit_order() -> None:
    exchange = _DummyExchange()
    manager = ExchangeBuyManager(_DummyLogger(), get_exchange=lambda: exchange)

    order = await manager.execute_market_buy(
        {
            "symbol": "CVC/USDC",
            "ordertype": "market",
            "side": "buy",
            "amount": "286",
            "price": "0.01955",
            "maximum_buy_price": 0.019598,
        }
    )

    assert order is not None
    assert order["ordertype"] == "limit"
    assert exchange.last_create_order is not None
    assert exchange.last_create_order["ordertype"] == "limit"
    assert exchange.last_create_order["price"] == "0.01960"
    assert exchange.last_create_order["params"] == {"timeInForce": "IOC"}


@pytest.mark.asyncio
async def test_unfilled_capped_recovery_buy_is_not_finalized() -> None:
    exchange = _DummyExchange()
    exchange.next_filled = 0.0
    exchange.next_status = "open"
    manager = ExchangeBuyManager(_DummyLogger(), get_exchange=lambda: exchange)

    order = await manager.execute_market_buy(
        {
            "symbol": "CVC/USDC",
            "ordertype": "market",
            "side": "buy",
            "amount": "286",
            "price": "0.01955",
            "maximum_buy_price": 0.019598,
        }
    )

    assert order is None
    assert exchange.cancel_order_calls == 1


@pytest.mark.asyncio
async def test_unfilled_capped_buy_cancel_failure_stays_pending() -> None:
    exchange = _DummyExchange()
    exchange.next_filled = 0.0
    exchange.next_status = "open"

    async def fail_cancel(_order_id: str, _symbol: str) -> None:
        exchange.cancel_order_calls += 1
        raise ccxt.InvalidOrder("cancel outcome unresolved")

    exchange.cancel_order = fail_cancel  # type: ignore[method-assign]
    manager = ExchangeBuyManager(_DummyLogger(), get_exchange=lambda: exchange)

    with pytest.raises(ExchangePostSubmissionFailure) as raised:
        await manager.execute_market_buy(
            {
                "operation_id": "buy-capped-pending",
                "client_order_id": "mw-buy-capped-pending",
                "symbol": "CVC/USDC",
                "ordertype": "market",
                "side": "buy",
                "amount": "286",
                "price": "0.01955",
                "maximum_buy_price": 0.019598,
            }
        )

    assert raised.value.order["id"] == "buy-1"
    assert raised.value.operation_id == "buy-capped-pending"
    assert exchange.cancel_order_calls == 1


@pytest.mark.asyncio
async def test_malformed_capped_buy_fill_stays_pending() -> None:
    exchange = _DummyExchange()
    exchange.next_filled = "not-a-number"
    manager = ExchangeBuyManager(_DummyLogger(), get_exchange=lambda: exchange)

    with pytest.raises(ExchangePostSubmissionFailure) as raised:
        await manager.execute_market_buy(
            {
                "operation_id": "buy-malformed-fill",
                "client_order_id": "mw-buy-malformed-fill",
                "symbol": "CVC/USDC",
                "ordertype": "market",
                "side": "buy",
                "amount": "286",
                "price": "0.01955",
                "maximum_buy_price": 0.019598,
            }
        )

    assert raised.value.order["id"] == "buy-1"
    assert raised.value.operation_id == "buy-malformed-fill"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("omit_filled", "filled", "status"),
    [
        (True, None, "canceled"),
        (False, 0.0, "closed"),
        (False, -1.0, "canceled"),
        (False, float("nan"), "canceled"),
    ],
)
async def test_invalid_fill_capped_buy_stays_pending(
    omit_filled: bool,
    filled: float | None,
    status: str,
) -> None:
    exchange = _DummyExchange()
    exchange.omit_filled = omit_filled
    exchange.next_filled = filled
    exchange.next_status = status
    manager = ExchangeBuyManager(_DummyLogger(), get_exchange=lambda: exchange)

    with pytest.raises(ExchangePostSubmissionFailure) as raised:
        await manager.execute_market_buy(
            {
                "operation_id": "buy-ambiguous-fill",
                "client_order_id": "mw-buy-ambiguous-fill",
                "symbol": "CVC/USDC",
                "ordertype": "market",
                "side": "buy",
                "amount": "286",
                "price": "0.01955",
                "maximum_buy_price": 0.019598,
            }
        )

    assert raised.value.order["id"] == "buy-1"
    assert raised.value.operation_id == "buy-ambiguous-fill"


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

    async def fake_resolve_symbol(symbol: str) -> str:
        return symbol

    result = await manager.finalize_market_buy(
        order={"symbol": "BTC/USDT", "id": "buy-1"},
        config={"dry_run": True, "fee_deduction": False},
        context=BuyFinalizationContext(
            parse_order_status=fake_parse_order_status,
            get_precision_for_symbol=fake_get_precision_for_symbol,
            resolve_symbol=fake_resolve_symbol,
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

    async def fake_resolve_symbol(symbol: str) -> str:
        return symbol

    result = await manager.finalize_market_buy(
        order={"symbol": "ETH/USDT", "id": "buy-2"},
        config={"dry_run": False, "fee_deduction": True},
        context=BuyFinalizationContext(
            parse_order_status=fake_parse_order_status,
            get_precision_for_symbol=fake_get_precision_for_symbol,
            resolve_symbol=fake_resolve_symbol,
            get_demo_taker_fee_for_symbol=lambda _symbol: 0.0,
        ),
    )

    assert result is not None
    assert result["precision"] == 4
    assert result["fees"] == 0.001
    assert result["amount_fee"] == 0.0
    assert result["amount"] == 3.0
    assert exchange.fetch_trading_fee_calls == 1
