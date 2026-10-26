"""Tests for resuming local persistence from reconciled placements."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from service.order_payloads import build_buy_trade_payload
from service.placement_intents import PlacementAction
from service.placement_recovery import PlacementRecoveryHandler


class _FakeExchange:
    def __init__(self) -> None:
        self.buy_result: dict[str, Any] | None = None
        self.sell_result: dict[str, Any] | None = None
        self.buy_calls = 0
        self.sell_calls = 0

    async def build_spot_buy_order_status(
        self,
        _evidence: dict[str, Any],
        _request: dict[str, Any],
        _config: dict[str, Any],
    ) -> dict[str, Any] | None:
        self.buy_calls += 1
        return self.buy_result

    async def build_spot_sell_order_status(
        self,
        _payload: dict[str, Any],
        _config: dict[str, Any],
    ) -> dict[str, Any] | None:
        self.sell_calls += 1
        return self.sell_result


class _FakeTrades:
    def __init__(self) -> None:
        self.open_rows: list[dict[str, Any]] = []
        self.trade_data: dict[str, Any] | None = None
        self.set_calls: list[dict[str, Any]] = []
        self.clear_calls: list[dict[str, Any]] = []

    async def set_tp_limit_order(
        self,
        symbol: str,
        **kwargs: Any,
    ) -> bool:
        self.set_calls.append({"symbol": symbol, **kwargs})
        return True

    async def get_trades_for_orders(self, _symbol: str) -> dict[str, Any] | None:
        return self.trade_data

    async def get_open_trades_by_symbol(
        self,
        _symbol: str,
    ) -> list[dict[str, Any]]:
        return self.open_rows

    async def clear_tp_limit_order(
        self,
        symbol: str,
        **kwargs: Any,
    ) -> bool:
        self.clear_calls.append({"symbol": symbol, **kwargs})
        return True


class _FakeIntents:
    def __init__(self) -> None:
        self.transitions: list[tuple[str, str]] = []

    async def transition(self, operation_id: str, state: Any) -> None:
        self.transitions.append((operation_id, str(state)))


def _intent(
    action: PlacementAction,
    *,
    request: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        operation_id=f"{action.value}-operation",
        action=action.value,
        symbol="BTC/USDC",
        exchange_order_id="exchange-order",
        requested_amount=1.5,
        maximum_price=101.0,
        request_json=json.dumps(request or {}),
        result_json=json.dumps(result or {}),
    )


def _handler() -> tuple[
    PlacementRecoveryHandler,
    _FakeExchange,
    _FakeTrades,
    _FakeIntents,
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[tuple[str, dict[str, Any]]],
]:
    exchange = _FakeExchange()
    trades = _FakeTrades()
    intents = _FakeIntents()
    buys: list[dict[str, Any]] = []
    sells: list[dict[str, Any]] = []
    partials: list[tuple[str, dict[str, Any]]] = []

    async def finalize_buy(
        payload: dict[str, Any], *_args: Any, **_kwargs: Any
    ) -> bool:
        buys.append(payload)
        return True

    async def finalize_sell(
        payload: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        sells.append(payload)

    async def persist_fallback(
        _evidence: dict[str, Any],
        _config: dict[str, Any],
        _operation_id: str,
    ) -> bool:
        return True

    handler = PlacementRecoveryHandler(
        exchange=exchange,
        trades=trades,
        validate_buy=lambda payload: (
            bool(payload.get("price")) and bool(payload.get("amount"))
        ),
        validate_sell=lambda payload: payload.get("type") == "sold_check",
        finalize_buy=finalize_buy,
        finalize_sell=finalize_sell,
        build_limit_sell_payload=lambda trade, evidence: {**trade, **evidence},
        persist_limit_fallback=persist_fallback,
    )
    return handler, exchange, trades, intents, buys, sells, partials


@pytest.mark.asyncio
async def test_recovered_buy_is_normalized_and_persisted() -> None:
    handler, exchange, _trades, _intents, buys, _sells, _partials = _handler()
    exchange.buy_result = {"symbol": "BTC/USDC", "price": 100.0, "amount": 0.1}

    result = await handler.resume(
        _intent(PlacementAction.BUY, request={"symbol": "BTC/USDC"}),
        {"id": "buy-1", "status": "closed"},
        {},
    )

    assert result is True
    assert exchange.buy_calls == 1
    assert buys[0]["amount"] == 0.1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("normalized_evidence", "request_percentage", "normalized_percentage"),
    [
        (False, None, None),
        (True, None, None),
        (False, -8.0, None),
        (True, -8.0, None),
        (False, -8.0, -7.0),
    ],
)
# Value: protects=buy recovery preserves context precedence and sizing provenance;
# fails_when=saved acknowledgement replaces request or fallback replaces normalized;
# why_new=existing recovery test exercises missing context only;
# seam=none
async def test_legacy_buy_recovers_local_metadata_from_saved_ack(
    normalized_evidence: bool,
    request_percentage: float | None,
    normalized_percentage: float | None,
) -> None:
    handler, exchange, _trades, _intents, buys, _sells, _partials = _handler()
    request = {
        "symbol": "BTC/USDC",
        "botname": "asap",
        "ordertype": "limit",
        "baseorder": False,
        "safetyorder": True,
        "order_count": 1,
        "direction": "long",
        "side": "buy",
    }
    if request_percentage is not None:
        request["so_percentage"] = request_percentage
    context = {
        "so_percentage": -4.5,
        "strategy_slug": "ema_low",
        "baseline_order_size": 20.0,
        "entry_size_applied": True,
        "entry_size_reason_code": "entry_scaled",
        "entry_size_fallback_applied": False,
        "entry_size_fallback_reason": "",
    }
    fill = {
        "id": "buy-1",
        "orderid": "buy-1",
        "status": "closed",
        "timestamp": 1000,
        "ordersize": 10.0,
        "fees": 0.001,
        "precision": 4,
        "amount_fee": 0.0,
        "price": 100.0,
        "amount": 0.1,
    }
    exchange.buy_result = {**request, **fill}
    if normalized_percentage is not None:
        exchange.buy_result["so_percentage"] = normalized_percentage
    expected_request_percentage = (
        request_percentage if request_percentage is not None else -4.5
    )
    expected_percentage = (
        normalized_percentage
        if normalized_percentage is not None
        else expected_request_percentage
    )

    async def persist(payload: dict[str, Any], *_args: Any, **kwargs: Any) -> bool:
        buys.append(build_buy_trade_payload(payload))
        assert kwargs["original_order"]["so_percentage"] == expected_request_percentage
        for key in context.keys() - {"so_percentage"}:
            assert payload[key] == context[key]
        return True

    handler = replace(handler, finalize_buy=persist)
    result = await handler.resume(
        _intent(
            PlacementAction.BUY,
            request=request,
            result=context,
        ),
        fill if normalized_evidence else {"id": "buy-1", "status": "closed"},
        {},
    )
    assert result is True
    assert buys[0]["so_percentage"] == expected_percentage
    assert buys[0]["strategy_slug"] == "ema_low"


@pytest.mark.asyncio
@pytest.mark.parametrize("percentage", [{}, {"so_percentage": None}])
async def test_legacy_safety_buy_without_percentage_requires_repair(
    percentage: dict[str, Any],
) -> None:
    handler, exchange, _trades, _intents, buys, _sells, _partials = _handler()
    with pytest.raises(ValueError, match="restore the original value"):
        await handler.resume(
            _intent(
                PlacementAction.BUY,
                request={"symbol": "BTC/USDC", "safetyorder": True, **percentage},
            ),
            {"id": "buy-1", "status": "closed"},
            {},
        )
    assert exchange.buy_calls == 0
    assert buys == []


@pytest.mark.asyncio
async def test_legacy_base_buy_without_percentage_keeps_unknown_value() -> None:
    handler, _exchange, _trades, _intents, buys, _sells, _partials = _handler()
    assert await handler.resume(
        _intent(PlacementAction.BUY, request={"baseorder": True}),
        {"fees": 0.001, "precision": 4, "amount": 0.1, "price": 100.0},
        {},
    )
    assert buys[0]["so_percentage"] is None


@pytest.mark.asyncio
async def test_recovered_market_sell_is_persisted() -> None:
    handler, exchange, _trades, _intents, _buys, sells, _partials = _handler()
    exchange.sell_result = {
        "type": "sold_check",
        "symbol": "BTC/USDC",
        "total_amount": 1.0,
    }

    result = await handler.resume(
        _intent(PlacementAction.SELL, request={"symbol": "BTC/USDC"}),
        {"id": "sell-1", "status": "closed"},
        {},
    )

    assert result is True
    assert exchange.sell_calls == 1
    assert sells[0]["type"] == "sold_check"


@pytest.mark.asyncio
async def test_recovered_open_limit_sell_restores_trade_metadata() -> None:
    handler, _exchange, trades, _intents, _buys, _sells, _partials = _handler()

    result = await handler.resume(
        _intent(PlacementAction.LIMIT_SELL),
        {
            "id": "limit-1",
            "status": "open",
            "price": 101.0,
            "amount": 1.5,
        },
        {},
    )

    assert result is True
    assert trades.set_calls == [
        {
            "symbol": "BTC/USDC",
            "order_id": "limit-1",
            "price": 101.0,
            "amount": 1.5,
            "placement_operation_id": "limit_sell-operation",
        }
    ]


@pytest.mark.asyncio
async def test_recovered_filled_limit_sell_closes_trade() -> None:
    handler, exchange, trades, _intents, _buys, sells, _partials = _handler()
    trades.trade_data = {"symbol": "BTC/USDC", "total_cost": 90.0}
    exchange.sell_result = {
        "type": "sold_check",
        "symbol": "BTC/USDC",
        "total_amount": 1.0,
    }

    result = await handler.resume(
        _intent(PlacementAction.LIMIT_SELL),
        {"id": "limit-2", "status": "closed", "filled": 1.0},
        {},
    )

    assert result is True
    assert exchange.sell_calls == 1
    assert sells[0]["type"] == "sold_check"


@pytest.mark.asyncio
async def test_recovered_cancel_persists_partial_and_marks_intent() -> None:
    handler, _exchange, trades, _intents, _buys, _sells, _partials = _handler()
    trades.open_rows = [{"tp_limit_order_id": "limit-3"}]

    result = await handler.resume(
        _intent(PlacementAction.CANCEL),
        {"id": "limit-3", "status": "canceled", "filled": 0.2},
        {},
    )

    assert result is True
    assert trades.clear_calls == [
        {
            "symbol": "BTC/USDC",
            "placement_operation_id": "cancel-operation",
            "exchange_status": {
                "id": "limit-3",
                "status": "canceled",
                "filled": 0.2,
            },
        }
    ]


@pytest.mark.asyncio
async def test_recovered_cancel_that_filled_closes_trade() -> None:
    handler, exchange, trades, _intents, _buys, sells, _partials = _handler()
    trades.trade_data = {"symbol": "BTC/USDC", "total_cost": 90.0}
    exchange.sell_result = {
        "type": "sold_check",
        "symbol": "BTC/USDC",
        "total_amount": 1.0,
    }

    result = await handler.resume(
        _intent(PlacementAction.CANCEL),
        {
            "id": "limit-4",
            "status": "closed",
            "filled": 1.0,
            "amount": 1.0,
        },
        {},
    )

    assert result is True
    assert exchange.sell_calls == 1
    assert sells[0]["type"] == "sold_check"
    assert trades.clear_calls == []


@pytest.mark.asyncio
async def test_unknown_recovery_action_fails_closed() -> None:
    handler, _exchange, _trades, _intents, _buys, _sells, _partials = _handler()
    intent = _intent(PlacementAction.BUY)
    intent.action = "unknown"

    assert await handler.resume(intent, {}, {}) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("fee_deduction", [False, True])
async def test_real_dca_buy_finalizer_matches_normal_and_recovered_order(
    monkeypatch, caplog, dry_run, fee_deduction
):
    """Recovery uses the real fee policy without submitting another buy."""
    import logging
    from unittest.mock import AsyncMock

    from service.dca.exchange import DcaExchange

    adapter = DcaExchange()
    adapter.exchange = SimpleNamespace(
        close=AsyncMock(),
        fetch_trading_fee=AsyncMock(return_value={"taker": 0.001}),
        market=lambda _symbol: {"taker": 0.001},
    )
    monkeypatch.setattr(adapter, "_ensure_exchange", AsyncMock())
    monkeypatch.setattr(adapter, "_ensure_markets_loaded", AsyncMock())
    monkeypatch.setattr(adapter, "_get_price_for_symbol", AsyncMock(return_value="100"))
    monkeypatch.setattr(adapter, "_get_amount_from_symbol", AsyncMock(return_value="2"))
    monkeypatch.setattr(adapter, "_preflight_buy_funds", AsyncMock(return_value=True))
    monkeypatch.setattr(adapter, "_resolve_symbol", lambda symbol: symbol)
    monkeypatch.setattr(
        adapter,
        "_resolve_symbol_with_refresh",
        AsyncMock(side_effect=lambda symbol: symbol),
    )
    monkeypatch.setattr(adapter, "_get_precision_for_symbol", AsyncMock(return_value=8))
    monkeypatch.setattr(
        adapter,
        "_is_notional_below_minimum",
        lambda *_args, **_kwargs: (False, 5.0, 200.0),
    )
    parsed = {
        "symbol": "BTC/USDC",
        "amount": 2.0,
        "total_amount": 2.0,
        "base_fee": 0.1,
        "price": 100.0,
        "orderid": "fill-1",
        "ordersize": 200.0,
        "timestamp": 1000,
    }
    monkeypatch.setattr(adapter, "_parse_order_status", AsyncMock(return_value=parsed))
    evidence = {"id": "fill-1", "symbol": "BTC/USDC", "status": "closed", "filled": 2.0}
    submit = AsyncMock(side_effect=lambda order: {**order, **evidence})
    monkeypatch.setattr(adapter, "_execute_market_buy", submit)
    private_metadata = "private-plugin-metadata-must-not-be-logged"
    request = {
        "symbol": "BTC/USDC",
        "side": "buy",
        "ordertype": "market",
        "ordersize": 200.0,
        "metadata_json": json.dumps({"note": private_metadata}),
    }
    config = {"dry_run": dry_run, "fee_deduction": fee_deduction}
    caplog.set_level(logging.DEBUG, logger="exchange")
    normal = await adapter.create_spot_market_buy(dict(request), config)
    handler, _exchange, _trades, _intents, buys, _sells, _partials = _handler()
    handler = replace(handler, exchange=adapter)
    assert await handler.resume(
        _intent(PlacementAction.BUY, request=request), evidence, config
    )
    assert normal is not None
    for key in (
        "symbol",
        "orderid",
        "amount",
        "amount_fee",
        "fees",
        "precision",
        "metadata_json",
    ):
        assert buys[0][key] == normal[key]
    assert normal["amount"] == pytest.approx(2.0 if fee_deduction else 1.9)
    assert submit.await_count == 1
    assert "Finalized DCA buy" in caplog.text
    assert private_metadata not in caplog.text
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", [PlacementAction.SELL, PlacementAction.LIMIT_SELL, PlacementAction.CANCEL]
)
@pytest.mark.parametrize("filled", [1.5, 2.0])
async def test_real_dca_sell_finalizer_matches_normal_and_recovered_order(
    monkeypatch, action, filled
):
    """Rebuilt full/partial sales retain metrics and executions, never resubmit."""
    from unittest.mock import AsyncMock

    from service.dca.exchange import DcaExchange

    adapter = DcaExchange()
    submit = AsyncMock(
        return_value={"id": "sell-1", "status": "closed", "filled": filled}
    )
    adapter.exchange = SimpleNamespace(
        close=AsyncMock(),
        create_market_sell_order=submit,
        amount_to_precision=lambda _symbol, amount: str(amount),
        market=lambda _symbol: {"limits": {"cost": {"min": 5.0}}},
    )
    monkeypatch.setattr(adapter, "_ensure_exchange", AsyncMock())
    monkeypatch.setattr(adapter, "_ensure_markets_loaded", AsyncMock())
    monkeypatch.setattr(
        adapter,
        "_resolve_symbol_with_refresh",
        AsyncMock(side_effect=lambda symbol: symbol),
    )
    monkeypatch.setattr(
        adapter, "_resolve_sell_amount", AsyncMock(return_value=("BTC/USDC", 2.0))
    )
    monkeypatch.setattr(adapter, "_log_remaining_sell_dust", AsyncMock())
    monkeypatch.setattr(
        adapter,
        "_is_notional_below_minimum",
        lambda *_args, **_kwargs: (False, 5.0, 240.0),
    )
    parsed = {
        "symbol": "BTC/USDC",
        "side": "sell",
        "total_amount": filled,
        "price": 120.0,
        "ordersize": filled * 120.0,
        "orderid": "sell-1",
        "timestamp": 1000,
        "base_fee": 0.01,
    }
    monkeypatch.setattr(adapter, "_parse_order_status", AsyncMock(return_value=parsed))
    request = {
        "symbol": "BTC/USDC",
        "side": "sell",
        "total_amount": 2.0,
        "requested_total_amount": 2.0,
        "total_cost": 200.0,
        "actual_pnl": 19.5,
        "current_price": 120.0,
    }
    normal = await adapter.create_spot_market_sell(dict(request), {})
    evidence = {
        "id": "sell-1",
        "symbol": "BTC/USDC",
        "status": "closed",
        "filled": filled,
        "amount": 2.0,
    }
    handler, _exchange, trades, _intents, _buys, sells, _partials = _handler()
    trades.trade_data = dict(request)
    handler = replace(handler, exchange=adapter)
    result = await handler.resume(_intent(action, request=request), evidence, {})
    rebuilt = await adapter.build_spot_sell_order_status({**request, **evidence}, {})
    assert rebuilt == normal
    assert rebuilt is not None and rebuilt["executions"]
    if filled == 2.0:
        assert result and sells[0] == normal
        assert normal["profit"] == 40.0
        assert normal["profit_percent"] == 20.0
    else:
        # Existing recovery refuses a partial close payload as a completed sale.
        assert not result and not sells
        assert normal["partial_filled_amount"] == 1.5
        assert normal["remaining_amount"] == 0.5
    assert submit.await_count == 1
    await adapter.close()


# Value: protects=limit completion and partial fallback retain close history totals;
# fails_when=moved callbacks lose a fill, its fee, or submit the remainder twice;
# why_new=manager tests replace finalization and recovery tests start after fills;
# seam=none;
# no_claim=provider acceptance or database atomicity (mocked exchange evidence;
# existing SQLite persistence tests cover the storage transaction).
@pytest.mark.asyncio
@pytest.mark.parametrize("partial_timeout", [False, True])
async def test_real_dca_limit_callbacks_preserve_close_history(
    monkeypatch, partial_timeout
):
    """Wire real limit, fallback, finalizer and history projection together."""
    from unittest.mock import AsyncMock

    from service.dca.exchange import DcaExchange
    from service.order_payloads import build_closed_trade_payloads

    adapter = DcaExchange()
    limit_fill = 1.5 if partial_timeout else 2.0
    limit_evidence = {
        "id": "limit-1",
        "symbol": "BTC/USDC",
        "status": "canceled" if partial_timeout else "closed",
        "filled": limit_fill,
        "remaining": 2.0 - limit_fill,
        "amount": 2.0,
        "average": 120.0,
        "price": 120.0,
    }
    market_submit = AsyncMock(
        return_value={"id": "market-1", "status": "closed", "filled": 0.5}
    )
    adapter.exchange = SimpleNamespace(
        close=AsyncMock(),
        create_market_sell_order=market_submit,
        fetch_order=AsyncMock(return_value={**limit_evidence, "status": "open"}),
        amount_to_precision=lambda _symbol, amount: str(amount),
        price_to_precision=lambda _symbol, price: str(price),
    )
    monkeypatch.setattr(adapter, "_ensure_exchange", AsyncMock())
    monkeypatch.setattr(adapter, "_ensure_markets_loaded", AsyncMock())
    monkeypatch.setattr(
        adapter,
        "_resolve_symbol_with_refresh",
        AsyncMock(side_effect=lambda symbol: symbol),
    )
    monkeypatch.setattr(
        adapter,
        "_resolve_sell_amount",
        AsyncMock(side_effect=lambda symbol, amount: (symbol, amount)),
    )
    monkeypatch.setattr(adapter, "_log_remaining_sell_dust", AsyncMock())
    monkeypatch.setattr(
        adapter, "_is_notional_below_minimum", lambda *_a, **_k: (False, 5.0, 240.0)
    )
    place_limit = AsyncMock(return_value={"id": "limit-1", "ordertype": "limit"})
    monkeypatch.setattr(adapter._limit_order_manager, "execute_limit_sell", place_limit)
    monkeypatch.setattr(
        adapter._limit_sell_manager,
        "wait_for_limit_sell_fill",
        AsyncMock(return_value=None if partial_timeout else limit_evidence),
    )
    cancel = AsyncMock(return_value=limit_evidence)
    monkeypatch.setattr(adapter._limit_sell_manager, "cancel_order_and_confirm", cancel)

    async def parse_evidence(order, **_kwargs):
        is_limit = order["id"] == "limit-1"
        amount = limit_fill if is_limit else 0.5
        price = 120.0 if is_limit else 124.0
        return {
            "symbol": "BTC/USDC",
            "side": "sell",
            "total_amount": amount,
            "price": price,
            "ordersize": amount * price,
            "orderid": order["id"],
            "ordertype": "limit" if is_limit else "market",
            "timestamp": 2000 if is_limit else 3000,
            "base_fee": 0.015 if is_limit else 0.005,
            "metadata_json": json.dumps({"fill": order["id"]}),
        }

    monkeypatch.setattr(adapter, "_parse_order_status", parse_evidence)
    result = await adapter.create_spot_sell(
        {
            "symbol": "BTC/USDC",
            "total_amount": 2.0,
            "total_cost": 200.0,
            "actual_pnl": 20.0,
            "current_price": 120.0,
            "limit_price": 120.0,
        },
        {"sell_order_type": "limit", "limit_sell_fallback_to_market": True},
    )
    assert result is not None and result["type"] == "sold_check"
    history = build_closed_trade_payloads(result, so_count=0, open_timestamp_ms=1000)[
        "payload"
    ]
    expected_proceeds = 242.0 if partial_timeout else 240.0
    assert history["amount"] == 2.0
    assert history["cost"] == 200.0
    assert history["profit"] == pytest.approx(expected_proceeds - 200.0)
    assert history["tp_price"] == pytest.approx(expected_proceeds / 2.0)
    executions = history["sell_executions"]
    assert sum(row["ordersize"] for row in executions) == expected_proceeds
    assert [row["order_id"] for row in executions] == (
        ["limit-1", "market-1"] if partial_timeout else ["limit-1"]
    )
    assert [row["fee"] for row in executions] == (
        [0.015, 0.005] if partial_timeout else [0.015]
    )
    assert [json.loads(row["metadata_json"])["fill"] for row in executions] == (
        ["limit-1", "market-1"] if partial_timeout else ["limit-1"]
    )
    assert place_limit.await_count == 1
    assert cancel.await_count == int(partial_timeout)
    assert market_submit.await_count == int(partial_timeout)
    if partial_timeout:
        assert float(market_submit.await_args.args[1]) == 0.5
    await adapter.close()
