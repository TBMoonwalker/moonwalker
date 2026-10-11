"""Bybit EU recovery buys must respect its dynamic spot price band."""

import logging
import time
from unittest.mock import AsyncMock

import ccxt.async_support as ccxt
import pytest
from service.exchange import Exchange
from service.exchange_buy_manager import ExchangeBuyManager


def prepare(monkeypatch, bands=("0.07051",), exchange_id="bybiteu"):
    """Exercise the actual buy prechecks with deterministic exchange responses."""
    exchange = Exchange()
    client = ccxt.bybiteu()
    client.id = exchange_id
    client.markets = {
        "SEI/USDC": {
            "id": "SEIUSDC",
            "symbol": "SEI/USDC",
            "base": "SEI",
            "quote": "USDC",
            "spot": True,
            "precision": {"price": 0.00001, "amount": 1.0},
            "limits": {"cost": {"min": 5.0}},
            "info": {},
        }
    }
    client.public_get_v5_market_price_limit = AsyncMock(
        side_effect=[
            {
                "retCode": 0,
                "result": {
                    "symbol": "SEIUSDC",
                    "buyLmt": band,
                    "ts": str(int(time.time() * 1000)),
                },
            }
            for band in bands
        ]
    )
    exchange.exchange = client
    monkeypatch.setattr(exchange, "_Exchange__ensure_exchange", AsyncMock())
    monkeypatch.setattr(exchange, "_Exchange__ensure_markets_loaded", AsyncMock())
    monkeypatch.setattr(
        exchange,
        "_Exchange__resolve_symbol_with_refresh",
        AsyncMock(return_value="SEI/USDC"),
    )
    monkeypatch.setattr(
        exchange, "_Exchange__get_price_for_symbol", AsyncMock(return_value="0.069")
    )
    balance = AsyncMock(return_value=100.0)
    monkeypatch.setattr(exchange, "get_free_quote_balance", balance)
    client.create_order = AsyncMock(
        return_value={"id": "accepted", "filled": 72, "status": "closed"}
    )
    manager = ExchangeBuyManager(logging.getLogger("test"), lambda: client)
    monkeypatch.setattr(
        exchange, "_Exchange__execute_market_buy", manager.execute_market_buy
    )

    async def finalize(**kwargs):
        return kwargs["order"]

    monkeypatch.setattr(exchange._buy_manager, "finalize_market_buy", finalize)
    return exchange, client, balance


def intent(ceiling=0.07237, quote=5.08):
    return {
        "symbol": "SEI/USDC",
        "ordersize": quote,
        "maximum_buy_price": ceiling,
        "ordertype": "market",
        "side": "buy",
        "client_order_id": "test-client",
    }


@pytest.mark.asyncio
async def test_sei_rejection_repro_clamps_price_and_resizes(monkeypatch):
    exchange, client, balance = prepare(monkeypatch)

    async def reject_above_band(symbol, kind, side, amount, price, params):
        assert kind == "limit" and params["timeInForce"] == "IOC"
        if float(price) > 0.07051:
            raise ccxt.InvalidOrder(
                'bybiteu {"retCode":170193,"retMsg":"Buy order price cannot be higher than 0.07051USDC."}'
            )
        assert float(amount) == 72
        return {"id": "accepted", "filled": amount, "status": "closed"}

    client.create_order.side_effect = reject_above_band
    result = await exchange.create_spot_market_buy(intent(), {})
    assert result is not None
    assert result["maximum_buy_price"] == pytest.approx(0.07051)
    assert client.create_order.await_count == 1
    assert balance.await_count == 1
    client.public_get_v5_market_price_limit.assert_awaited_once_with(
        {"category": "spot", "symbol": "SEIUSDC"}
    )


@pytest.mark.asyncio
async def test_moving_band_gets_one_retry_with_fresh_prechecks(monkeypatch):
    exchange, client, balance = prepare(monkeypatch, bands=("0.07051", "0.07001"))
    client.create_order.side_effect = [
        ccxt.InvalidOrder('bybiteu {"retCode":170193,"retMsg":"price changed"}'),
        {"id": "accepted", "filled": 72, "status": "closed"},
    ]
    assert await exchange.create_spot_market_buy(intent(), {}) is not None
    assert [float(c.args[4]) for c in client.create_order.await_args_list] == [
        0.07051,
        0.07001,
    ]
    assert balance.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("band", ["0.070519", "0.08"])
async def test_band_rounds_down_and_never_raises_strategy_cap(monkeypatch, band):
    exchange, client, _ = prepare(monkeypatch, bands=(band,))
    result = await exchange.create_spot_market_buy(intent(), {})
    assert result is not None
    expected = 0.07051 if band == "0.070519" else 0.07237
    assert float(client.create_order.await_args.args[4]) == pytest.approx(expected)


@pytest.mark.asyncio
async def test_ask_above_band_never_submits(monkeypatch):
    exchange, client, balance = prepare(monkeypatch, bands=("0.068",))
    assert await exchange.create_spot_market_buy(intent(), {}) is None
    client.create_order.assert_not_awaited()
    balance.assert_not_awaited()
    assert (
        exchange.get_last_buy_precheck_result()["reason"]
        == "execution_price_above_maximum"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        ccxt.InvalidOrder('{"retCode":170193}'),
        ccxt.InvalidOrder('{"retCode":170140}'),
        ccxt.RequestTimeout("uncertain acceptance"),
    ],
)
async def test_retries_bounded_and_only_known_price_rejections(monkeypatch, failure):
    exchange, client, _ = prepare(monkeypatch, bands=("0.07051", "0.07001"))
    client.create_order.side_effect = failure
    try:
        result = await exchange.create_spot_market_buy(intent(), {})
        assert result is None
    except Exception as exc:
        from service.exchange_capabilities import ExchangeSubmissionIndeterminate

        assert isinstance(failure, ccxt.RequestTimeout)
        assert isinstance(exc, ExchangeSubmissionIndeterminate)
    expected = 2 if "170193" in str(failure) else 1
    assert client.create_order.await_count == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_result",
    [
        None,
        {"retCode": 1},
        {"retCode": 0, "result": {"symbol": "SEIUSDC", "buyLmt": "NaN"}},
        {"retCode": 0, "result": {"symbol": "OTHER", "buyLmt": "0.07"}},
        {"retCode": 0, "result": {"symbol": "SEIUSDC", "buyLmt": "0.07", "ts": "1"}},
    ],
)
async def test_invalid_or_stale_band_fails_before_submission(monkeypatch, bad_result):
    exchange, client, _ = prepare(monkeypatch)
    client.public_get_v5_market_price_limit.side_effect = None
    client.public_get_v5_market_price_limit.return_value = bad_result
    assert await exchange.create_spot_market_buy(intent(), {}) is None
    client.create_order.assert_not_awaited()
    assert (
        exchange.get_last_buy_precheck_result()["reason"]
        == "exchange_price_band_unavailable"
    )


@pytest.mark.asyncio
async def test_binance_capped_buy_keeps_existing_path(monkeypatch):
    exchange, client, _ = prepare(monkeypatch, exchange_id="binance")
    assert await exchange.create_spot_market_buy(intent(), {}) is not None
    client.public_get_v5_market_price_limit.assert_not_awaited()
    assert float(client.create_order.await_args.args[4]) == pytest.approx(0.07237)


@pytest.mark.asyncio
async def test_reduced_band_rechecks_minimum_notional(monkeypatch):
    exchange, client, _ = prepare(monkeypatch)
    assert await exchange.create_spot_market_buy(intent(quote=5.0), {}) is None
    client.create_order.assert_not_awaited()
    assert (
        exchange.get_last_buy_precheck_result()["reason"]
        == "amount_below_minimum_notional"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        ccxt.RequestTimeout("price band timeout"),
        ccxt.NotSupported("endpoint unavailable"),
    ],
)
async def test_price_band_read_failure_never_submits(monkeypatch, error):
    exchange, client, balance = prepare(monkeypatch)
    client.public_get_v5_market_price_limit.side_effect = error
    assert await exchange.create_spot_market_buy(intent(), {}) is None
    client.create_order.assert_not_awaited()
    balance.assert_not_awaited()
    assert (
        exchange.get_last_buy_precheck_result()["reason"]
        == "exchange_price_band_unavailable"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_guard", ["ask", "funds"])
async def test_retry_rechecks_ask_and_funds_before_second_submission(
    monkeypatch, changed_guard
):
    exchange, client, balance = prepare(monkeypatch, bands=("0.07051", "0.07001"))
    client.create_order.side_effect = ccxt.InvalidOrder('{"retCode":170193}')
    if changed_guard == "ask":
        monkeypatch.setattr(
            exchange,
            "_Exchange__get_price_for_symbol",
            AsyncMock(side_effect=["0.069", "0.0703"]),
        )
    else:
        balance.side_effect = [100.0, 0.0]
    assert await exchange.create_spot_market_buy(intent(), {}) is None
    assert client.create_order.await_count == 1
    reason = exchange.get_last_buy_precheck_result()["reason"]
    assert reason == (
        "execution_price_above_maximum"
        if changed_guard == "ask"
        else "insufficient_quote_balance"
    )
