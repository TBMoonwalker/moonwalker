import json
from typing import Any, cast

import pytest
import service.order_persistence as persistence_module
from service.persistence_records import TradePersistenceRecord
from service.placement_intents import PlacementIntentState
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError


def _trade_record(**overrides: Any) -> TradePersistenceRecord:
    payload: dict[str, Any] = {
        "timestamp": "1714726800000",
        "ordersize": 100.0,
        "fee": 0.0,
        "precision": 8,
        "amount": 1.0,
        "amount_fee": 0.0,
        "price": 100.0,
        "symbol": "BTC/USDC",
        "orderid": "test-order",
        "bot": "test",
        "ordertype": "market",
        "baseorder": True,
        "safetyorder": False,
        "order_count": 0,
        "so_percentage": None,
        "direction": "long",
        "side": "buy",
    }
    payload.update(overrides)
    return cast(TradePersistenceRecord, payload)


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
        _trade_record(
            signal_name="asap",
            metadata_json='{"entry_sizing":{"applied":true}}',
        ),
        create_open_trade=True,
    )

    assert _DummyTradesModel.created_payload is not None
    assert _DummyTradesModel.created_payload["symbol"] == "BTC/USDC"
    assert _DummyTradesModel.created_payload["price"] == 100.0
    assert _DummyTradesModel.created_payload["deal_id"]
    assert "signal_name" not in _DummyTradesModel.created_payload
    assert "metadata_json" not in _DummyTradesModel.created_payload
    assert _DummyOpenTradesCreateModel.created_symbol == "BTC/USDC"
    assert _DummyOpenTradesCreateModel.created_payload is not None
    assert _DummyOpenTradesCreateModel.created_payload["deal_id"]
    assert (
        _DummyOpenTradesCreateModel.created_payload["dca_sizing_mode"]
        == "legacy_factors"
    )
    assert _DummyOpenTradesCreateModel.created_payload["dca_reference_price"] == 100.0
    assert (
        _DummyOpenTradesCreateModel.created_payload["execution_history_complete"]
        is True
    )
    assert _DummyTradeExecutionsModel.created_payload is not None
    assert _DummyTradeExecutionsModel.created_payload["role"] == "base_order"
    assert _DummyTradeExecutionsModel.created_payload["signal_name"] == "asap"
    assert (
        _DummyTradeExecutionsModel.created_payload["metadata_json"]
        == '{"entry_sizing":{"applied":true}}'
    )


def test_open_trade_dca_defaults_preserve_recovery_policy_snapshot() -> None:
    policy = {
        "mode": "recovery_target",
        "atr_timeframe": "4h",
        "atr_length": 14,
        "maximum_deal_quote": 250.0,
    }

    defaults = persistence_module._build_open_trade_dca_defaults(
        {
            "price": 0.568,
            "metadata_json": json.dumps({"dca_policy": policy}),
        }
    )

    assert defaults["dca_sizing_mode"] == "recovery_target"
    assert defaults["dca_reference_price"] == 0.568
    assert json.loads(defaults["dca_policy_json"])["maximum_deal_quote"] == 250.0


async def _async_value(value: Any) -> Any:
    return value


@pytest.mark.asyncio
async def test_unsellable_outcome_and_placement_persist_atomically(tmp_path) -> None:
    """A failed remainder archive must roll back every sell-side mutation."""
    import model

    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'unsellable-atomic.sqlite'}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()
    try:
        await model.Trades.create(
            timestamp="1778000000000",
            ordersize=10.0,
            fee=0.0,
            precision=8,
            amount=1.0,
            amount_fee=0.0,
            price=10.0,
            symbol="LINK/USDC",
            orderid="buy-before-unsellable",
            bot="atomic_test",
            ordertype="market",
            baseorder=True,
            safetyorder=False,
            order_count=0,
            so_percentage=None,
            direction="long",
            side="buy",
            deal_id="deal-unsellable",
        )
        await model.OpenTrades.create(
            symbol="LINK/USDC",
            deal_id="deal-unsellable",
            amount=1.0,
            cost=10.0,
            execution_history_complete=True,
        )
        await model.PlacementIntent.create(
            operation_id="unsellable-sell",
            client_order_id="mw-unsellable-sell",
            exchange_name="binance",
            symbol="LINK/USDC",
            action="sell",
            side="sell",
            order_type="market",
            state=PlacementIntentState.FILLED.value,
        )
        existing_archive = await model.UnsellableTrades.create(
            symbol="STALE/USDC",
            deal_id="deal-unsellable",
        )
        closed_payload = {
            "symbol": "LINK/USDC",
            "amount": 0.9,
            "cost": 9.0,
            "profit": 0.9,
        }
        unsellable_payload = {
            "symbol": "LINK/USDC",
            "amount": 0.1,
            "cost": 1.0,
        }

        with pytest.raises(IntegrityError):
            await persistence_module.persist_unsellable_remainder(
                "LINK/USDC",
                unsellable_payload,
                partial_amount=0.9,
                partial_proceeds=9.9,
                closed_trade_payload=closed_payload,
                placement_operation_id="unsellable-sell",
            )

        assert await model.Trades.filter(symbol="LINK/USDC").count() == 1
        assert await model.OpenTrades.filter(symbol="LINK/USDC").count() == 1
        assert await model.TradeExecutions.all().count() == 0
        assert await model.ClosedTrades.all().count() == 0
        assert await model.UnsellableTrades.all().count() == 1
        placement = await model.PlacementIntent.get(operation_id="unsellable-sell")
        assert placement.state == PlacementIntentState.FILLED.value

        await existing_archive.delete()
        await persistence_module.persist_unsellable_remainder(
            "LINK/USDC",
            unsellable_payload,
            partial_amount=0.9,
            partial_proceeds=9.9,
            closed_trade_payload=closed_payload,
            placement_operation_id="unsellable-sell",
        )

        assert await model.Trades.filter(symbol="LINK/USDC").count() == 0
        assert await model.OpenTrades.filter(symbol="LINK/USDC").count() == 0
        assert await model.TradeExecutions.all().count() == 1
        assert await model.ClosedTrades.all().count() == 1
        assert await model.UnsellableTrades.all().count() == 1
        await placement.refresh_from_db()
        assert placement.state == PlacementIntentState.PERSISTED.value
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_tp_cancel_partial_fill_and_intent_persist_atomically(tmp_path) -> None:
    """Cancel fill bookkeeping and metadata clearing share one transaction."""
    import model

    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'tp-cancel-atomic.sqlite'}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()
    try:
        await model.OpenTrades.create(
            symbol="XPL/USDC",
            deal_id="deal-tp-cancel",
            amount=2.0,
            cost=20.0,
            execution_history_complete=True,
            tp_limit_order_id="tp-limit-1",
            tp_limit_order_price=11.0,
            tp_limit_order_amount=2.0,
        )
        intent = await model.PlacementIntent.create(
            operation_id="cancel-tp-limit",
            client_order_id="mw-cancel-tp-limit",
            exchange_order_id="tp-limit-1",
            exchange_name="binance",
            symbol="XPL/USDC",
            action="cancel",
            side="sell",
            order_type="limit",
            state=PlacementIntentState.REJECTED.value,
        )
        exchange_status = {
            "id": "tp-limit-1",
            "symbol": "XPL/USDC",
            "status": "canceled",
            "filled": 0.4,
            "amount": 2.0,
            "average": 11.0,
            "cost": 4.4,
            "timestamp": 1_742_000_000_123,
        }

        with pytest.raises(ValueError, match="Cannot mark placement"):
            await persistence_module.persist_tp_limit_cancellation(
                "XPL/USDC",
                exchange_status,
                placement_operation_id="cancel-tp-limit",
            )

        open_trade = await model.OpenTrades.get(symbol="XPL/USDC")
        assert open_trade.sold_amount == pytest.approx(0.0)
        assert open_trade.tp_limit_order_id == "tp-limit-1"
        assert await model.TradeExecutions.all().count() == 0

        intent.state = PlacementIntentState.ACCEPTED.value
        await intent.save(update_fields=["state"])
        persisted = await persistence_module.persist_tp_limit_cancellation(
            "XPL/USDC",
            exchange_status,
            placement_operation_id="cancel-tp-limit",
        )

        assert persisted is True
        await open_trade.refresh_from_db()
        assert open_trade.sold_amount == pytest.approx(0.4)
        assert open_trade.sold_proceeds == pytest.approx(4.4)
        assert open_trade.tp_limit_order_id is None
        execution = await model.TradeExecutions.get(deal_id="deal-tp-cancel")
        assert execution.order_id == "tp-limit-1"
        await intent.refresh_from_db()
        assert intent.state == PlacementIntentState.PERSISTED.value
    finally:
        await Tortoise.close_connections()


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

    async def fake_schedule(symbol: str, payload: dict[str, Any]) -> None:
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
        _trade_record(),
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
async def test_persisted_buy_survives_optional_ai_follow_up_failure(
    monkeypatch,
) -> None:
    _DummyTradesModel.created_payload = None
    _DummyOpenTradesCreateModel.created_payload = None

    async def fake_run_sqlite(operation, _name) -> None:
        await operation()

    async def fail_ai_persistence(*_args: Any) -> None:
        raise RuntimeError("AI ledger unavailable")

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
        "persist_entry_evaluation",
        fail_ai_persistence,
    )
    gate = persistence_module.AiTrustEntryGate(
        allowed=True,
        evaluated=True,
        provider_status="scored",
    )

    await persistence_module.persist_buy_trade(
        "BTC/USDC",
        _trade_record(),
        create_open_trade=True,
        entry_evaluation=gate,
    )

    assert _DummyTradesModel.created_payload is not None
    assert _DummyOpenTradesCreateModel.created_payload is not None


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
            _trade_record(),
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
        _trade_record(
            timestamp="1714726800000",
            ordersize=100.0,
            amount=1.0,
            price=100.0,
            baseorder=True,
            safetyorder=False,
        ),
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
