from typing import Any

import pytest
import service.order_persistence as persistence_module


class _DummyTradesModel:
    created_payload: dict[str, Any] | None = None

    @classmethod
    async def create(cls, using_db: Any = None, **kwargs: Any) -> None:
        cls.created_payload = kwargs


class _DummyOpenTradesCreateModel:
    created_symbol: str | None = None

    @classmethod
    async def create(cls, using_db: Any = None, **kwargs: Any) -> None:
        cls.created_symbol = str(kwargs.get("symbol"))


class _DummyOpenTradesFilter:
    def __init__(self, update_result: int) -> None:
        self.update_result = update_result

    def using_db(self, _conn: Any) -> "_DummyOpenTradesFilter":
        return self

    async def update(self, **kwargs: Any) -> int:
        return self.update_result

    async def delete(self) -> None:
        return None


class _DummyOpenTradesModel:
    update_result = 1

    @classmethod
    def filter(cls, **kwargs: Any) -> _DummyOpenTradesFilter:
        return _DummyOpenTradesFilter(cls.update_result)


class _DummyTx:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_persist_buy_trade_creates_open_trade_when_requested(
    monkeypatch,
) -> None:
    _DummyTradesModel.created_payload = None
    _DummyOpenTradesCreateModel.created_symbol = None

    async def fake_run_sqlite(operation, _name) -> None:
        await operation()

    monkeypatch.setattr(
        persistence_module, "run_sqlite_write_with_retry", fake_run_sqlite
    )
    monkeypatch.setattr(persistence_module, "in_transaction", lambda: _DummyTx())
    monkeypatch.setattr(persistence_module.model, "Trades", _DummyTradesModel)
    monkeypatch.setattr(
        persistence_module.model,
        "OpenTrades",
        _DummyOpenTradesCreateModel,
    )

    await persistence_module.persist_buy_trade(
        "BTC/USDC",
        {"symbol": "BTC/USDC", "price": 100.0},
        create_open_trade=True,
    )

    assert _DummyTradesModel.created_payload == {
        "symbol": "BTC/USDC",
        "price": 100.0,
    }
    assert _DummyOpenTradesCreateModel.created_symbol == "BTC/USDC"


@pytest.mark.asyncio
async def test_persist_manual_buy_add_requires_matching_open_trade(
    monkeypatch,
) -> None:
    async def fake_run_sqlite(operation, _name) -> None:
        await operation()

    monkeypatch.setattr(
        persistence_module, "run_sqlite_write_with_retry", fake_run_sqlite
    )
    monkeypatch.setattr(persistence_module, "in_transaction", lambda: _DummyTx())
    monkeypatch.setattr(persistence_module.model, "Trades", _DummyTradesModel)
    monkeypatch.setattr(persistence_module.model, "OpenTrades", _DummyOpenTradesModel)

    _DummyOpenTradesModel.update_result = 0

    with pytest.raises(ValueError, match="No open trade found for BTC/USDC."):
        await persistence_module.persist_manual_buy_add(
            "BTC/USDC",
            {"symbol": "BTC/USDC"},
            {"amount": 1.5},
        )
