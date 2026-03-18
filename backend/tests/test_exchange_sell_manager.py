"""Tests for exchange sell manager."""

import pytest
from service.exchange_contexts import MarketSellExecutionContext, SellRoutingContext
from service.exchange_sell_manager import ExchangeSellManager


class _DummyLogger:
    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass

    def error(self, *_args, **_kwargs) -> None:
        pass


class _DummyExchange:
    def __init__(self) -> None:
        self.market_sell_calls = 0

    def amount_to_precision(self, _symbol: str, amount: float) -> str:
        return f"{amount:.3f}"

    async def create_market_sell_order(
        self, _symbol: str, _amount: float
    ) -> dict[str, object]:
        self.market_sell_calls += 1
        return {"id": "sell-1", "symbol": _symbol}


@pytest.mark.asyncio
async def test_create_spot_market_sell_initializes_exchange_before_lookup() -> None:
    holder: dict[str, _DummyExchange | None] = {"exchange": None}
    manager = ExchangeSellManager(
        logger=_DummyLogger(),
        get_exchange=lambda: holder["exchange"],
    )

    async def fake_ensure_exchange(_config: dict[str, object]) -> None:
        holder["exchange"] = _DummyExchange()

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_resolve_symbol(symbol: str) -> str:
        return symbol

    async def fake_resolve_sell_amount(
        _symbol: str,
        _requested_amount: float,
    ) -> tuple[str, float]:
        return "GMX/USDC", 1.0

    async def fake_get_price_for_symbol(_symbol: str) -> str:
        return "10.0"

    async def fake_log_remaining_sell_dust(_symbol: str) -> None:
        return None

    async def fake_build_sell_order_status(
        order: dict[str, object],
    ) -> dict[str, object] | None:
        return {"type": "sold_check", "id": order.get("id")}

    status = await manager.create_spot_market_sell(
        order={
            "symbol": "GMX/USDC",
            "total_amount": 1.0,
            "total_cost": 7.29,
            "actual_pnl": 0.0,
        },
        config={},
        context=MarketSellExecutionContext(
            ensure_exchange=fake_ensure_exchange,
            ensure_markets_loaded=fake_ensure_markets_loaded,
            resolve_symbol=fake_resolve_symbol,
            resolve_sell_amount=fake_resolve_sell_amount,
            reduce_amount_by_step=lambda _symbol, amount, _steps: amount,
            is_notional_below_minimum=lambda _symbol, _amount, _price: (
                False,
                None,
                0.0,
            ),
            get_price_for_symbol=fake_get_price_for_symbol,
            log_remaining_sell_dust=fake_log_remaining_sell_dust,
            build_sell_order_status=fake_build_sell_order_status,
        ),
    )

    assert status == {"type": "sold_check", "id": "sell-1"}


@pytest.mark.asyncio
async def test_create_spot_sell_returns_partial_when_fallback_disabled() -> None:
    exchange = _DummyExchange()
    manager = ExchangeSellManager(
        logger=_DummyLogger(),
        get_exchange=lambda: exchange,
    )

    async def fake_limit_sell(
        _order: dict[str, object], _config: dict[str, object]
    ) -> dict[str, object]:
        return {
            "requires_market_fallback": True,
            "limit_cancel_confirmed": True,
            "symbol": "ERA/USDC",
            "remaining_amount": 100.0,
            "partial_filled_amount": 40.0,
            "partial_avg_price": 0.1515,
        }

    async def fake_market_sell(
        _order: dict[str, object], _config: dict[str, object]
    ) -> dict[str, object] | None:
        raise AssertionError("market fallback should not run")

    async def fake_guard(_order: dict[str, object], _config: dict[str, object]) -> bool:
        return True

    result = await manager.create_spot_sell(
        order={"symbol": "ERA/USDC"},
        config={"sell_order_type": "limit", "limit_sell_fallback_to_market": False},
        context=SellRoutingContext(
            create_spot_limit_sell=fake_limit_sell,
            create_spot_market_sell=fake_market_sell,
            can_fallback_to_market_sell=fake_guard,
        ),
    )

    assert result is not None
    assert result["type"] == "partial_sell"
    assert result["partial_filled_amount"] == 40.0


@pytest.mark.asyncio
async def test_create_spot_market_sell_skips_below_notional() -> None:
    exchange = _DummyExchange()
    manager = ExchangeSellManager(
        logger=_DummyLogger(),
        get_exchange=lambda: exchange,
    )

    async def fake_ensure_exchange(_config: dict[str, object]) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_resolve_symbol(symbol: str) -> str:
        return symbol

    async def fake_resolve_sell_amount(
        _symbol: str,
        _requested_amount: float,
    ) -> tuple[str, float]:
        return "GMX/USDC", 0.679

    async def fake_get_price_for_symbol(_symbol: str) -> str:
        return "7.13"

    async def fake_log_remaining_sell_dust(_symbol: str) -> None:
        return None

    async def fake_build_sell_order_status(
        _order: dict[str, object],
    ) -> dict[str, object] | None:
        return {"type": "sold_check"}

    result = await manager.create_spot_market_sell(
        order={
            "symbol": "GMX/USDC",
            "total_amount": 1.70338025,
            "total_cost": 7.29,
            "actual_pnl": 0.0,
        },
        config={},
        context=MarketSellExecutionContext(
            ensure_exchange=fake_ensure_exchange,
            ensure_markets_loaded=fake_ensure_markets_loaded,
            resolve_symbol=fake_resolve_symbol,
            resolve_sell_amount=fake_resolve_sell_amount,
            reduce_amount_by_step=lambda _symbol, amount, _steps: amount,
            is_notional_below_minimum=lambda _symbol, _amount, _price: (
                True,
                5.0,
                4.84,
            ),
            get_price_for_symbol=fake_get_price_for_symbol,
            log_remaining_sell_dust=fake_log_remaining_sell_dust,
            build_sell_order_status=fake_build_sell_order_status,
        ),
    )

    assert result is not None
    assert result["type"] == "partial_sell"
    assert result["symbol"] == "GMX/USDC"
    assert result["remaining_amount"] == pytest.approx(0.679)
    assert exchange.market_sell_calls == 0


@pytest.mark.asyncio
async def test_create_spot_market_sell_skips_below_fallback_min_price() -> None:
    exchange = _DummyExchange()
    manager = ExchangeSellManager(
        logger=_DummyLogger(),
        get_exchange=lambda: exchange,
    )

    async def fake_ensure_exchange(_config: dict[str, object]) -> None:
        return None

    async def fake_ensure_markets_loaded() -> None:
        return None

    async def fake_resolve_symbol(symbol: str) -> str:
        return symbol

    async def fake_resolve_sell_amount(
        _symbol: str,
        _requested_amount: float,
    ) -> tuple[str, float]:
        return "XPL/USDC", 101.9

    async def fake_get_price_for_symbol(_symbol: str) -> str:
        return "0.106"

    async def fake_log_remaining_sell_dust(_symbol: str) -> None:
        return None

    async def fake_build_sell_order_status(
        _order: dict[str, object],
    ) -> dict[str, object] | None:
        return {"type": "sold_check"}

    result = await manager.create_spot_market_sell(
        order={
            "symbol": "XPL/USDC",
            "total_amount": 101.9,
            "total_cost": 11.99,
            "actual_pnl": 6.0,
            "current_price": 0.106,
            "fallback_min_price": 0.11,
        },
        config={},
        context=MarketSellExecutionContext(
            ensure_exchange=fake_ensure_exchange,
            ensure_markets_loaded=fake_ensure_markets_loaded,
            resolve_symbol=fake_resolve_symbol,
            resolve_sell_amount=fake_resolve_sell_amount,
            reduce_amount_by_step=lambda _symbol, amount, _steps: amount,
            is_notional_below_minimum=lambda _symbol, _amount, _price: (
                False,
                None,
                0.0,
            ),
            get_price_for_symbol=fake_get_price_for_symbol,
            log_remaining_sell_dust=fake_log_remaining_sell_dust,
            build_sell_order_status=fake_build_sell_order_status,
        ),
    )

    assert result is not None
    assert result["type"] == "partial_sell"
    assert result["symbol"] == "XPL/USDC"
    assert result["remaining_amount"] == pytest.approx(101.9)
    assert exchange.market_sell_calls == 0
