"""Regression coverage for final outcomes and durable optional delivery."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from service.feedback_accounting import execution_accounting, merge_accounting_metadata
from service.signal_settings import SignalSettingsError, canonicalize_signal_settings
from service.trade_feedback import (
    build_feedback_payload,
    deliver_feedback,
    enqueue_feedback,
    feedback_destination,
)
from tortoise import Tortoise
from tortoise.transactions import in_transaction

CONFIG = {
    "signal": "websocket_signal",
    "dry_run": True,
    "signal_settings": {
        "feedback_enabled": True,
        "websocket_url": "wss://pathfinder.example/v1/signals/stream?token=test",
    },
}
ENDPOINT = "https://pathfinder.example/v1/feedback/closed-trades"
SUMMARY = {
    "deal_id": "deal-1",
    "symbol": "BTC/USDC",
    "open_date": "2026-09-26 10:00:00",
    "close_date": "2026-09-26 11:00:00",
    "execution_history_complete": True,
}


def execution(side, cost, fee, currency, price=100.0):
    """Build a ledger row from normalized CCXT fees."""
    accounting = execution_accounting(
        [{"side": side, "price": price, "fee": {"cost": fee, "currency": currency}}],
        "BTC/USDC",
    )
    metadata = {
        "websocket_signal": {
            "signal_id": "sig-1",
            "exchange": "binance",
            "feedback_endpoint": ENDPOINT,
        }
    }
    return SimpleNamespace(
        side=side,
        ordersize=cost,
        metadata_json=merge_accounting_metadata(metadata, accounting),
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_demo_and_live_use_same_gate(dry_run):
    config = {**CONFIG, "dry_run": dry_run}
    assert feedback_destination(config) == (ENDPOINT, {"Authorization": "Bearer test"})
    assert feedback_destination({**config, "signal": "asap"}) is None
    assert (
        feedback_destination({**config, "signal_settings": {"feedback_enabled": False}})
        is None
    )
    assert feedback_destination({**config, "signal_settings": {}}) is None


def test_boolean_setting_is_strict():
    with pytest.raises(SignalSettingsError):
        canonicalize_signal_settings({"feedback_enabled": "false"})


def test_net_profit_does_not_double_count_base_buy_fee():
    # Buy 1 BTC for 100, lose .001 BTC as fee; sell remaining .999 at 110.
    result = build_feedback_payload(
        SUMMARY,
        [
            execution("buy", 100, 0.001, "BTC"),
            execution("sell", 109.89, 0.10989, "USDC", 110),
        ],
    )
    assert result["entry_value_quote"] == 100
    assert result["net_profit_quote"] == pytest.approx(9.78011)
    assert result["fees_quote"] == pytest.approx(0.20989)
    assert result["opened_at"].endswith("+00:00")


def test_quote_buy_fees_dca_partial_sells_and_incomplete_history():
    result = build_feedback_payload(
        {**SUMMARY, "execution_history_complete": False},
        [
            execution("buy", 100, 0.1, "USDC"),
            execution("buy", 50, 0.05, "USDC"),
            execution("sell", 80, 0.08, "USDC"),
            execution("sell", 90, 0.09, "USDC"),
        ],
    )
    assert result["entry_value_quote"] == pytest.approx(150.15)
    assert result["net_profit_quote"] == pytest.approx(19.68)
    assert result["net_return_percent"] == pytest.approx(19.68 / 150.15 * 100)
    assert result["execution_history_complete"] is False


def test_unvalued_fee_is_not_reported_as_net_profit():
    with pytest.raises(ValueError, match="incomplete_fee_accounting"):
        build_feedback_payload(
            SUMMARY,
            [execution("buy", 100, 0.01, "BNB"), execution("sell", 110, 0.11, "USDC")],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [
        (200, "sent"),
        (409, "rejected"),
        (404, "rejected"),
        (401, "rejected"),
        (422, "rejected"),
        (429, "pending"),
        (503, "pending"),
    ],
)
async def test_delivery_response_and_immutable_retries(status, expected):
    payload = json.dumps({"signal_id": "sig-1", "deal_id": "deal-1"})
    row = SimpleNamespace(
        endpoint=ENDPOINT,
        deal_id="deal-1",
        payload_json=payload,
        status="pending",
        attempts=0,
        save=AsyncMock(),
    )
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            status,
            json={
                "accepted": True,
                "created": False,
                "deal_id": "deal-1",
                "signal_id": "sig-1",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await deliver_feedback(row, CONFIG, client)
        if expected == "pending":
            await deliver_feedback(row, CONFIG, client)
    assert row.status == expected
    assert all(request.content.decode() == payload for request in requests)
    assert row.payload_json == payload
    assert row.next_attempt_at > 0


@pytest.mark.asyncio
async def test_disabled_or_changed_provider_never_sends():
    row = SimpleNamespace(endpoint=ENDPOINT, status="pending")
    client = SimpleNamespace(post=AsyncMock())
    await deliver_feedback(row, {**CONFIG, "signal": "asap"}, client)
    await deliver_feedback(
        row, {**CONFIG, "signal_settings": {"feedback_enabled": False}}, client
    )
    await deliver_feedback(
        row,
        {
            **CONFIG,
            "signal_settings": {
                "feedback_enabled": True,
                "websocket_url": "wss://another.example/",
            },
        },
        client,
    )
    client.post.assert_not_called()


@pytest.mark.asyncio
async def test_outbox_is_transactional_and_duplicate_safe(tmp_path):
    import model

    db_url = f"sqlite://{tmp_path / 'feedback.sqlite'}"
    await Tortoise.init(db_url=db_url, modules={"models": ["model"]})
    try:
        await Tortoise.generate_schemas()
        for index, row in enumerate(
            [execution("buy", 100, 0.1, "USDC"), execution("sell", 110, 0.11, "USDC")]
        ):
            await model.TradeExecutions.create(
                deal_id="deal-1",
                symbol="BTC/USDC",
                side=row.side,
                role="base_order" if index == 0 else "final_sell",
                timestamp="1",
                price=100,
                amount=1,
                ordersize=row.ordersize,
                metadata_json=row.metadata_json,
            )
        with pytest.raises(RuntimeError):
            async with in_transaction() as conn:
                await enqueue_feedback(SUMMARY, CONFIG, conn)
                raise RuntimeError("simulate rollback")
        assert await model.TradeFeedback.all().count() == 0
        async with in_transaction() as conn:
            await enqueue_feedback(SUMMARY, CONFIG, conn)
            await enqueue_feedback(SUMMARY, CONFIG, conn)
        assert await model.TradeFeedback.all().count() == 1
        payload = (await model.TradeFeedback.get(deal_id="deal-1")).payload_json
        await Tortoise.close_connections()
        await Tortoise.init(db_url=db_url, modules={"models": ["model"]})
        row = await model.TradeFeedback.get(deal_id="deal-1")
        assert row.status == "pending"
        assert row.payload_json == payload
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
@pytest.mark.parametrize("response_kind", ["network", "bad_json", "wrong_receipt"])
async def test_no_acknowledgement_never_loses_outcome(response_kind):
    """Only a matching acknowledgement may remove a pending delivery."""
    row = SimpleNamespace(
        endpoint=ENDPOINT,
        deal_id="deal-1",
        payload_json=json.dumps({"signal_id": "sig-1"}),
        status="pending",
        attempts=0,
        save=AsyncMock(),
    )

    def handle(request):
        if response_kind == "network":
            raise httpx.ConnectError("secret URL must not be logged", request=request)
        if response_kind == "bad_json":
            return httpx.Response(200, content=b"not JSON")
        return httpx.Response(
            200, json={"accepted": True, "deal_id": "wrong", "signal_id": "sig-1"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await deliver_feedback(row, CONFIG, client)
    assert row.status == "pending"
    row.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_final_close_persists_outbox_and_cleans_open_state(tmp_path, monkeypatch):
    """Exercise the actual close transaction rather than just the outbox helper."""
    import model
    import service.order_persistence as persistence

    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'close.sqlite'}", modules={"models": ["model"]}
    )
    try:
        await Tortoise.generate_schemas()
        await model.OpenTrades.create(
            symbol="BTC/USDC", deal_id="deal-1", execution_history_complete=True
        )
        buy = execution("buy", 100, 0.1, "USDC")
        sell = execution("sell", 110, 0.11, "USDC")
        await model.TradeExecutions.create(
            deal_id="deal-1",
            symbol="BTC/USDC",
            side="buy",
            role="base_order",
            timestamp="1",
            price=100,
            amount=1,
            ordersize=100,
            metadata_json=buy.metadata_json,
        )
        monkeypatch.setattr(persistence, "archive_replay_candles_for_deal", AsyncMock())
        monkeypatch.setattr(
            persistence, "_repair_replay_archive_after_commit", AsyncMock()
        )
        monkeypatch.setattr(
            persistence, "has_prediction_for_deal", AsyncMock(return_value=False)
        )
        await persistence.persist_closed_trade(
            "BTC/USDC",
            {
                **SUMMARY,
                "profit": 10,
                "cost": 100,
                "sell_executions": [
                    {
                        "symbol": "BTC/USDC",
                        "side": "sell",
                        "role": "final_sell",
                        "price": 110,
                        "amount": 1,
                        "ordersize": 110,
                        "metadata_json": sell.metadata_json,
                    }
                ],
            },
            feedback_config=CONFIG,
        )
        assert await model.OpenTrades.all().count() == 0
        assert await model.ClosedTrades.all().count() == 1
        row = await model.TradeFeedback.get(deal_id="deal-1")
        assert row.status == "pending"
        assert json.loads(row.payload_json)["net_profit_quote"] == pytest.approx(9.79)
        assert "Bearer" not in row.payload_json
        assert "token" not in row.endpoint
    finally:
        await Tortoise.close_connections()


@pytest.mark.parametrize(
    "url",
    [
        "https://provider.example",
        "wss://user:pass@provider.example/",
        "wss:///missing-host",
    ],
)
def test_feedback_rejects_invalid_or_credentialed_destinations(url):
    config = {
        **CONFIG,
        "signal_settings": {"feedback_enabled": True, "websocket_url": url},
    }
    assert feedback_destination(config) is None


def test_authorization_header_overrides_url_token_and_is_not_persisted():
    config = {
        **CONFIG,
        "signal_settings": {
            **CONFIG["signal_settings"],
            "headers": {"authorization": "Bearer header-token"},
        },
    }
    endpoint, headers = feedback_destination(config)
    assert endpoint == ENDPOINT
    assert headers == {"Authorization": "Bearer header-token"}


@pytest.mark.parametrize(
    "fee",
    [
        None,
        {"cost": None},
        {"cost": "bad"},
        {"cost": float("inf")},
        {"cost": -1},
        {"cost": 1, "currency": "BNB"},
    ],
)
def test_invalid_fee_information_blocks_accounting(fee):
    result = execution_accounting(
        [{"side": "sell", "price": 100, "fee": fee}], "BTC/USDC"
    )
    assert result["complete"] is False


def test_zero_fee_and_multiple_fee_currencies_preserve_cash_flow():
    result = execution_accounting(
        [
            {
                "side": "buy",
                "price": 100,
                "fees": [
                    {"cost": 0.001, "currency": "BTC"},
                    {"cost": 0.2, "currency": "USDC"},
                ],
            },
            {"side": "sell", "price": 110, "fee": {"cost": 0, "currency": None}},
        ],
        "BTC/USDC",
    )
    assert result == {
        "complete": True,
        "fees_quote": pytest.approx(0.3),
        "external_buy_fees": 0.2,
        "sell_fees": 0.0,
    }


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("exchange", "signal_exchange_mismatch"),
        ("symbol", "signal_symbol_mismatch"),
        ("provenance", "missing_signal_provenance"),
        ("cost", "invalid_outcome_amounts"),
    ],
)
def test_invalid_outcome_is_rejected_before_delivery(mutation, error):
    buy = execution("buy", 100, 0, "USDC")
    metadata = json.loads(buy.metadata_json)
    if mutation == "exchange":
        metadata["websocket_signal"]["execution_exchange"] = "another-exchange"
    elif mutation == "symbol":
        metadata["websocket_signal"]["symbol"] = "ETH/USDC"
    elif mutation == "provenance":
        metadata.pop("websocket_signal")
    else:
        buy.ordersize = 0
    buy.metadata_json = json.dumps(metadata)
    with pytest.raises(ValueError, match=error):
        build_feedback_payload(SUMMARY, [buy, execution("sell", 110, 0, "USDC")])


@pytest.mark.parametrize("use_lookup", [True, False])
def test_normalized_sell_accounting_survives_final_execution_payload(use_lookup):
    from datetime import UTC, datetime

    from service.exchange_helpers import aggregate_matched_trades
    from service.exchange_order_lookup import build_parsed_order_status
    from service.exchange_sell_status import finalize_sell_order_status
    from service.order_payloads import build_final_sell_executions

    fill = {
        "id": "sell-1",
        "order": "sell-1",
        "symbol": "BTC/USDC",
        "side": "sell",
        "timestamp": 1000,
        "amount": 1.0,
        "price": 110.0,
        "cost": 110.0,
        "fee": {"cost": 0.11, "currency": "USDC"},
    }
    parsed = build_parsed_order_status(
        fill, aggregate_matched_trades([fill], "BTC/USDC") if use_lookup else None
    )
    # Normal finalization and the fallback payload path both retain exact metadata.
    normalized = finalize_sell_order_status(parsed, total_cost=100, actual_pnl=10)
    execution_rows = build_final_sell_executions(
        normalized, closed_at=datetime.now(UTC)
    )
    fallback_rows = (
        build_final_sell_executions(
            {**normalized, "executions": []}, closed_at=datetime.now(UTC)
        )
        if use_lookup
        else []
    )
    for row in execution_rows + fallback_rows:
        assert json.loads(row["metadata_json"])["feedback_accounting"][
            "sell_fees"
        ] == pytest.approx(0.11)


@pytest.mark.asyncio
async def test_worker_rechecks_toggle_between_rows_and_closes_client(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    import service.trade_feedback as feedback
    from service.config import Config

    snapshots = iter([CONFIG, CONFIG, {**CONFIG, "signal": "asap"}])
    state = SimpleNamespace(snapshot=lambda: next(snapshots))
    monkeypatch.setattr(Config, "instance", AsyncMock(return_value=state))
    rows = [
        SimpleNamespace(
            endpoint=ENDPOINT,
            deal_id=f"deal-{index}",
            payload_json=json.dumps({"signal_id": "sig-1"}),
            status="pending",
            attempts=0,
            save=AsyncMock(),
        )
        for index in range(2)
    ]
    query = MagicMock()
    query.order_by.return_value = query
    query.limit = AsyncMock(return_value=rows)
    filter_mock = MagicMock(return_value=query)
    monkeypatch.setattr(feedback.model.TradeFeedback, "filter", filter_mock)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200, json={"accepted": True, "deal_id": "deal-0", "signal_id": "sig-1"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(feedback.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(
        feedback.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError)
    )
    with pytest.raises(asyncio.CancelledError):
        await feedback.run_feedback_worker()
    assert len(requests) == 1
    assert rows[0].status == "sent"
    assert rows[1].attempts == 0
    rows[1].save.assert_not_called()
    query.limit.assert_awaited_once_with(25)
    assert filter_mock.call_args.kwargs["status"] == "pending"
    assert filter_mock.call_args.kwargs["endpoint"] == ENDPOINT
    assert client.is_closed


@pytest.mark.asyncio
async def test_worker_pauses_disabled_and_recovers_database_failure(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    import service.trade_feedback as feedback
    from service.config import Config
    from tortoise.exceptions import OperationalError

    snapshots = iter([{**CONFIG, "signal": "asap"}, CONFIG, CONFIG])
    state = SimpleNamespace(snapshot=lambda: next(snapshots))
    monkeypatch.setattr(Config, "instance", AsyncMock(return_value=state))
    query = MagicMock()
    query.order_by.return_value = query
    query.limit = AsyncMock(return_value=[])
    filter_mock = MagicMock(
        side_effect=[OperationalError("database unavailable"), query]
    )
    monkeypatch.setattr(feedback.model.TradeFeedback, "filter", filter_mock)
    sleep = AsyncMock(side_effect=[None, None, asyncio.CancelledError])
    monkeypatch.setattr(feedback.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await feedback.run_feedback_worker()
    assert filter_mock.call_count == 2
    assert sleep.await_count == 3
    query.limit.assert_awaited_once_with(25)


@pytest.mark.asyncio
async def test_buy_finalization_preserves_signal_and_accounts_base_fee_once():
    from unittest.mock import MagicMock

    from service.exchange_buy_manager import ExchangeBuyManager
    from service.exchange_contexts import BuyFinalizationContext

    exchange = SimpleNamespace(
        fetch_trading_fee=AsyncMock(return_value={"taker": 0.001})
    )
    manager = ExchangeBuyManager(MagicMock(), get_exchange=lambda: exchange)
    for dry_run in (True, False):
        for fee_deduction in (True, False):
            accounting = execution_accounting(
                [
                    {
                        "side": "buy",
                        "price": 100,
                        "fee": {"cost": 0.001, "currency": "BTC"},
                    }
                ],
                "BTC/USDC",
            )
            parsed = {
                "symbol": "BTC/USDC",
                "amount": 1,
                "base_fee": 0.001,
                "price": 100,
                "metadata_json": merge_accounting_metadata(None, accounting),
            }
            result = await manager.finalize_market_buy(
                order={
                    "symbol": "BTC/USDC",
                    "metadata_json": json.dumps(
                        {
                            "websocket_signal": {"signal_id": "sig-1"},
                            "dca_policy": {"mode": "legacy_factors"},
                        }
                    ),
                },
                config={"dry_run": dry_run, "fee_deduction": fee_deduction},
                context=BuyFinalizationContext(
                    parse_order_status=AsyncMock(return_value=parsed),
                    get_precision_for_symbol=AsyncMock(return_value=6),
                    resolve_symbol=AsyncMock(return_value="BTC/USDC"),
                    get_demo_taker_fee_for_symbol=lambda _: 0.001,
                ),
            )
            metadata = json.loads(result["metadata_json"])
            assert metadata["websocket_signal"] == {"signal_id": "sig-1"}
            assert metadata["dca_policy"] == {"mode": "legacy_factors"}
            assert metadata["feedback_accounting"]["fees_quote"] == pytest.approx(0.1)
            assert metadata["feedback_accounting"][
                "external_buy_fees"
            ] == pytest.approx(0.1 if fee_deduction else 0)
            assert result["amount"] == pytest.approx(1 if fee_deduction else 0.999)


@pytest.mark.asyncio
@pytest.mark.parametrize("lookup_available", [True, False])
@pytest.mark.parametrize("multiple_fees", [True, False])
async def test_ccxt_base_fees_reach_inventory_and_feedback(
    lookup_available, multiple_fees
):
    """Fees-only fills and order fallbacks must reduce purchased inventory."""
    from unittest.mock import MagicMock

    from service.exchange_buy_manager import ExchangeBuyManager
    from service.exchange_contexts import BuyFinalizationContext
    from service.exchange_helpers import aggregate_matched_trades
    from service.exchange_order_lookup import build_parsed_order_status

    fee = {"cost": 0.001, "currency": "BTC"}
    fill = {
        "id": "order-1",
        "order": "order-1",
        "symbol": "BTC/USDC",
        "side": "buy",
        "amount": 1,
        "price": 100,
        "cost": 100,
        "timestamp": 1,
        "fee": None if multiple_fees else fee,
    }
    if multiple_fees:
        fill["fees"] = [fee]
    trade = aggregate_matched_trades([fill], "BTC/USDC") if lookup_available else None
    parsed = build_parsed_order_status(fill, trade)
    assert parsed["base_fee"] == pytest.approx(0.001)
    assert parsed["amount_fee"] == pytest.approx(0.001)
    manager = ExchangeBuyManager(MagicMock(), get_exchange=lambda: SimpleNamespace())
    result = await manager.finalize_market_buy(
        order={
            "symbol": "BTC/USDC",
            "metadata_json": execution("buy", 100, 0, "USDC").metadata_json,
        },
        config={"dry_run": True, "fee_deduction": False},
        context=BuyFinalizationContext(
            parse_order_status=AsyncMock(return_value=parsed),
            get_precision_for_symbol=AsyncMock(return_value=6),
            resolve_symbol=AsyncMock(return_value="BTC/USDC"),
            get_demo_taker_fee_for_symbol=lambda _: 0.001,
        ),
    )
    assert result["amount"] == pytest.approx(0.999)
    buy = SimpleNamespace(
        side="buy", ordersize=100, metadata_json=result["metadata_json"]
    )
    outcome = build_feedback_payload(
        SUMMARY, [buy, execution("sell", 0.999 * 110, 0.10989, "USDC", 110)]
    )
    assert outcome["net_profit_quote"] == pytest.approx(9.78011)
    assert outcome["fees_quote"] == pytest.approx(0.20989)
