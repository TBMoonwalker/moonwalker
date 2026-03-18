from typing import Any

import pytest
import service.orders as orders_module
from service.orders import Orders


class _DummyTradesModel:
    created_payload: dict[str, Any] | None = None

    @classmethod
    async def create(cls, using_db: Any = None, **kwargs: Any) -> None:
        cls.created_payload = kwargs


class _DummyOpenTradesFilter:
    def __init__(self, model_cls: type["_DummyOpenTradesModel"], symbol: str) -> None:
        self.model_cls = model_cls
        self.symbol = symbol

    def using_db(self, _conn: Any) -> "_DummyOpenTradesFilter":
        return self

    async def update(self, **kwargs: Any) -> int:
        self.model_cls.updated_symbol = self.symbol
        self.model_cls.updated_payload = kwargs
        return 1


class _DummyOpenTradesModel:
    updated_symbol: str | None = None
    updated_payload: dict[str, Any] | None = None

    @classmethod
    def filter(cls, **kwargs: Any) -> _DummyOpenTradesFilter:
        return _DummyOpenTradesFilter(cls, str(kwargs.get("symbol", "")))


class _DummyTx:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_receive_manual_buy_add_appends_safety_order(monkeypatch) -> None:
    _DummyTradesModel.created_payload = None
    _DummyOpenTradesModel.updated_symbol = None
    _DummyOpenTradesModel.updated_payload = None

    orders = Orders()

    async def fake_run_sqlite(operation, _name) -> None:
        await operation()

    monkeypatch.setattr(orders_module, "run_sqlite_write_with_retry", fake_run_sqlite)
    monkeypatch.setattr(orders_module, "in_transaction", lambda: _DummyTx())
    monkeypatch.setattr(orders_module.model, "Trades", _DummyTradesModel)
    monkeypatch.setattr(orders_module.model, "OpenTrades", _DummyOpenTradesModel)

    async def fake_get_open_trades_by_symbol(_symbol: str) -> list[dict[str, Any]]:
        return [
            {
                "symbol": "BTC/USDC",
                "so_count": 1,
                "amount": 1.0,
                "cost": 100.0,
            }
        ]

    async def fake_get_trades_by_symbol(_symbol: str) -> list[dict[str, Any]]:
        return [
            {"timestamp": "1000", "price": 100.0, "baseorder": True},
            {"timestamp": "2000", "price": 90.0, "safetyorder": True},
        ]

    async def fake_get_trades_for_orders(_symbol: str) -> dict[str, Any]:
        return {
            "safetyorders_count": 1,
            "bot": "asap_BTC/USDC",
            "ordertype": "market",
            "direction": "long",
        }

    monkeypatch.setattr(
        orders.trades,
        "get_open_trades_by_symbol",
        fake_get_open_trades_by_symbol,
    )
    monkeypatch.setattr(
        orders.trades, "get_trades_by_symbol", fake_get_trades_by_symbol
    )
    monkeypatch.setattr(
        orders.trades, "get_trades_for_orders", fake_get_trades_for_orders
    )

    result = await orders.receive_manual_buy_add(
        symbol="BTC/USDC",
        date_input="3000",
        price_raw=80.0,
        amount_raw=0.5,
        config={"tp": 1.0},
    )

    assert result["symbol"] == "BTC/USDC"
    assert result["timestamp"] == 3000000
    assert result["order_count"] == 2
    assert result["ordersize"] == pytest.approx(40.0)
    assert result["so_percentage"] == pytest.approx(round(((80 - 90) / 90) * 100, 2))

    assert _DummyTradesModel.created_payload is not None
    created = _DummyTradesModel.created_payload
    assert created["symbol"] == "BTC/USDC"
    assert created["baseorder"] is False
    assert created["safetyorder"] is True
    assert created["order_count"] == 2
    assert created["ordersize"] == pytest.approx(40.0)

    assert _DummyOpenTradesModel.updated_symbol == "BTC/USDC"
    assert _DummyOpenTradesModel.updated_payload is not None
    updated = _DummyOpenTradesModel.updated_payload
    assert updated["so_count"] == 2
    assert updated["amount"] == pytest.approx(1.5)
    assert updated["cost"] == pytest.approx(140.0)
    assert updated["avg_price"] == pytest.approx(140.0 / 1.5)
    assert updated["tp_price"] == pytest.approx((140.0 / 1.5) * 1.01)


@pytest.mark.asyncio
async def test_receive_manual_buy_add_requires_open_trade(monkeypatch) -> None:
    orders = Orders()

    async def fake_get_open_trades_by_symbol(_symbol: str) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        orders.trades,
        "get_open_trades_by_symbol",
        fake_get_open_trades_by_symbol,
    )

    with pytest.raises(ValueError, match="No open trade found"):
        await orders.receive_manual_buy_add(
            symbol="BTC/USDC",
            date_input="3000",
            price_raw=80.0,
            amount_raw=0.5,
            config={},
        )


@pytest.mark.asyncio
async def test_receive_manual_buy_add_rejects_older_date(monkeypatch) -> None:
    orders = Orders()

    async def fake_get_open_trades_by_symbol(_symbol: str) -> list[dict[str, Any]]:
        return [{"symbol": "BTC/USDC", "so_count": 0, "amount": 0.5, "cost": 50.0}]

    async def fake_get_trades_by_symbol(_symbol: str) -> list[dict[str, Any]]:
        return [{"timestamp": "5000000", "price": 100.0, "baseorder": True}]

    monkeypatch.setattr(
        orders.trades,
        "get_open_trades_by_symbol",
        fake_get_open_trades_by_symbol,
    )
    monkeypatch.setattr(
        orders.trades, "get_trades_by_symbol", fake_get_trades_by_symbol
    )

    with pytest.raises(ValueError, match="Date must be greater than or equal"):
        await orders.receive_manual_buy_add(
            symbol="BTC/USDC",
            date_input="4000",
            price_raw=80.0,
            amount_raw=0.5,
            config={},
        )
