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
    created_payload: dict[str, Any] | None = None

    @classmethod
    def filter(cls, **kwargs: Any) -> "_DummyMissingOpenTradesFilter":
        return _DummyMissingOpenTradesFilter()

    @classmethod
    async def create(cls, using_db: Any = None, **kwargs: Any) -> None:
        cls.created_symbol = str(kwargs.get("symbol"))
        cls.created_payload = kwargs


class _DummyMissingOpenTradesFilter:
    def using_db(self, _conn: Any) -> "_DummyMissingOpenTradesFilter":
        return self

    async def first(self) -> None:
        return None


class _DummyOpenTradesFilter:
    def __init__(self, update_result: int) -> None:
        self.update_result = update_result

    def using_db(self, _conn: Any) -> "_DummyOpenTradesFilter":
        return self

    async def update(self, **kwargs: Any) -> int:
        _DummyOpenTradesModel.updated_payload = kwargs
        return self.update_result

    async def delete(self) -> None:
        return None

    async def first(self) -> Any:
        return _DummyOpenTradeRow()


class _DummyOpenTradesModel:
    update_result = 1
    updated_payload: dict[str, Any] | None = None

    @classmethod
    def filter(cls, **kwargs: Any) -> _DummyOpenTradesFilter:
        return _DummyOpenTradesFilter(cls.update_result)


class _DummyTradeExecutionsModel:
    created_payload: dict[str, Any] | None = None

    @classmethod
    async def create(cls, using_db: Any = None, **kwargs: Any) -> None:
        cls.created_payload = kwargs


class _DummySpotCampaignsFilter:
    def using_db(self, _conn: Any) -> "_DummySpotCampaignsFilter":
        return self

    async def update(self, **_kwargs: Any) -> int:
        return 1


class _DummySpotCampaignsModel:
    @classmethod
    def filter(cls, **_kwargs: Any) -> _DummySpotCampaignsFilter:
        return _DummySpotCampaignsFilter()


class _DummyOpenTradeRow:
    deal_id = "a2f3a070-875a-49c3-87cf-06f9514dfac0"
    campaign_id = None
    execution_history_complete = True
    open_date = "2024-05-01 07:00:00+00:00"
    lifecycle_mode = "sidestep_reentry"


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
    _DummyOpenTradesCreateModel.created_payload = None
    _DummyTradeExecutionsModel.created_payload = None

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
    monkeypatch.setattr(
        persistence_module.model,
        "TradeExecutions",
        _DummyTradeExecutionsModel,
    )
    monkeypatch.setattr(
        persistence_module,
        "is_entry_observation_enabled",
        lambda: _async_value(False),
    )

    await persistence_module.persist_buy_trade(
        "BTC/USDC",
        {"symbol": "BTC/USDC", "price": 100.0},
        create_open_trade=True,
    )

    assert _DummyTradesModel.created_payload is not None
    assert _DummyTradesModel.created_payload["symbol"] == "BTC/USDC"
    assert _DummyTradesModel.created_payload["price"] == 100.0
    assert _DummyTradesModel.created_payload["deal_id"]
    assert _DummyOpenTradesCreateModel.created_symbol == "BTC/USDC"
    assert _DummyOpenTradesCreateModel.created_payload is not None
    assert _DummyOpenTradesCreateModel.created_payload["deal_id"]
    assert (
        _DummyOpenTradesCreateModel.created_payload["execution_history_complete"]
        is True
    )
    assert _DummyTradeExecutionsModel.created_payload is not None
    assert _DummyTradeExecutionsModel.created_payload["role"] == "buy"


async def _async_value(value: Any) -> Any:
    return value


@pytest.mark.asyncio
async def test_persist_buy_trade_schedules_ai_trust_after_open_trade_persistence(
    monkeypatch,
) -> None:
    _DummyTradesModel.created_payload = None
    _DummyOpenTradesCreateModel.created_symbol = None
    _DummyOpenTradesCreateModel.created_payload = None
    scheduled: list[dict[str, Any]] = []

    async def fake_run_sqlite(operation, _name) -> None:
        await operation()

    def fake_schedule(symbol: str, payload: dict[str, Any]) -> None:
        scheduled.append(
            {
                "symbol": symbol,
                "deal_id": payload.get("deal_id"),
                "open_trade_created": _DummyOpenTradesCreateModel.created_payload
                is not None,
            }
        )

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
    monkeypatch.setattr(
        persistence_module.model,
        "TradeExecutions",
        _DummyTradeExecutionsModel,
    )
    monkeypatch.setattr(
        persistence_module,
        "is_entry_observation_enabled",
        lambda: _async_value(True),
    )
    monkeypatch.setattr(
        persistence_module,
        "schedule_entry_observation",
        fake_schedule,
    )

    await persistence_module.persist_buy_trade(
        "BTC/USDC",
        {"symbol": "BTC/USDC", "price": 100.0},
        create_open_trade=True,
    )

    assert _DummyOpenTradesCreateModel.created_payload is not None
    assert scheduled == [
        {
            "symbol": "BTC/USDC",
            "deal_id": _DummyOpenTradesCreateModel.created_payload["deal_id"],
            "open_trade_created": True,
        }
    ]


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
    monkeypatch.setattr(
        persistence_module.model,
        "SpotCampaigns",
        _DummySpotCampaignsModel,
    )
    monkeypatch.setattr(
        persistence_module.model,
        "TradeExecutions",
        _DummyTradeExecutionsModel,
    )

    _DummyOpenTradesModel.update_result = 0

    with pytest.raises(ValueError, match="No open trade found for BTC/USDC."):
        await persistence_module.persist_manual_buy_add(
            "BTC/USDC",
            {"symbol": "BTC/USDC"},
            {"amount": 1.5},
        )


@pytest.mark.asyncio
async def test_persist_buy_trade_preserves_original_open_date_on_sidestep_reentry(
    monkeypatch,
) -> None:
    _DummyTradesModel.created_payload = None
    _DummyOpenTradesModel.updated_payload = None
    _DummyTradeExecutionsModel.created_payload = None

    async def fake_run_sqlite(operation, _name) -> None:
        await operation()

    monkeypatch.setattr(
        persistence_module, "run_sqlite_write_with_retry", fake_run_sqlite
    )
    monkeypatch.setattr(persistence_module, "in_transaction", lambda: _DummyTx())
    monkeypatch.setattr(persistence_module.model, "Trades", _DummyTradesModel)
    monkeypatch.setattr(persistence_module.model, "OpenTrades", _DummyOpenTradesModel)
    monkeypatch.setattr(
        persistence_module.model,
        "SpotCampaigns",
        _DummySpotCampaignsModel,
    )
    monkeypatch.setattr(
        persistence_module.model,
        "TradeExecutions",
        _DummyTradeExecutionsModel,
    )
    monkeypatch.setattr(
        persistence_module,
        "is_entry_observation_enabled",
        lambda: _async_value(False),
    )

    await persistence_module.persist_buy_trade(
        "BTC/USDC",
        {
            "symbol": "BTC/USDC",
            "timestamp": "1714726800000",
            "ordersize": 100.0,
            "amount": 1.0,
            "price": 100.0,
            "baseorder": True,
            "safetyorder": False,
        },
        create_open_trade=True,
        campaign_context={
            "campaign_id": "campaign-1",
            "lifecycle_mode": "sidestep_reentry",
            "started_at": "2024-05-01 07:00:00+00:00",
        },
    )

    assert _DummyOpenTradesModel.updated_payload is not None
    assert _DummyOpenTradesModel.updated_payload["open_date"] == (
        "2024-05-01 07:00:00+00:00"
    )
    assert _DummyOpenTradesModel.updated_payload["amount"] == 1.0
    assert _DummyOpenTradesModel.updated_payload["cost"] == 100.0
