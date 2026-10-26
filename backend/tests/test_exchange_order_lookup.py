"""Tests for typed exchange-order reconciliation lookups."""

from __future__ import annotations

from typing import Any

import ccxt.async_support as ccxt
import pytest
from service.exchange import Exchange
from service.exchange_capabilities import ExchangeOrderLookupStatus
from service.exchange_order_lookup import build_parsed_order_status


class _LookupExchange:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    async def fetch_order(
        self,
        order_id: str,
        symbol: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        self.calls.append((order_id, symbol, params))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _BybitLookupExchange:
    def __init__(
        self,
        *,
        open_orders: list[dict[str, Any]] | Exception | None = None,
        closed_orders: list[dict[str, Any]] | Exception | None = None,
        canceled_orders: list[dict[str, Any]] | Exception | None = None,
    ) -> None:
        self.results = {
            "open": open_orders or [],
            "closed": closed_orders or [],
            "canceled": canceled_orders or [],
        }
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    async def _fetch(
        self,
        status: str,
        symbol: str,
        _since: int | None,
        _limit: int | None,
        params: dict[str, str],
    ) -> list[dict[str, Any]]:
        self.calls.append((status, symbol, params))
        result = self.results[status]
        if isinstance(result, Exception):
            raise result
        return result

    async def fetch_open_orders(
        self,
        symbol: str,
        since: int | None,
        limit: int | None,
        params: dict[str, str],
    ) -> list[dict[str, Any]]:
        return await self._fetch("open", symbol, since, limit, params)

    async def fetch_closed_orders(
        self,
        symbol: str,
        since: int | None,
        limit: int | None,
        params: dict[str, str],
    ) -> list[dict[str, Any]]:
        return await self._fetch("closed", symbol, since, limit, params)

    async def fetch_canceled_orders(
        self,
        symbol: str,
        since: int | None,
        limit: int | None,
        params: dict[str, str],
    ) -> list[dict[str, Any]]:
        return await self._fetch("canceled", symbol, since, limit, params)


async def _noop_async(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _resolved_symbol(_symbol: str) -> str:
    return "BTC/USDC"


def _exchange_with_lookup(
    monkeypatch: pytest.MonkeyPatch,
    result: dict[str, Any] | Exception,
) -> tuple[Exchange, _LookupExchange]:
    service = Exchange()
    client = _LookupExchange(result)
    service.exchange = client
    monkeypatch.setattr(service, "_Exchange__ensure_exchange", _noop_async)
    monkeypatch.setattr(service, "_Exchange__ensure_markets_loaded", _noop_async)
    monkeypatch.setattr(
        service,
        "_Exchange__resolve_symbol_with_refresh",
        _resolved_symbol,
    )
    return service, client


def _exchange_with_client(
    monkeypatch: pytest.MonkeyPatch,
    client: Any,
) -> Exchange:
    service = Exchange()
    service.exchange = client
    monkeypatch.setattr(service, "_Exchange__ensure_exchange", _noop_async)
    monkeypatch.setattr(service, "_Exchange__ensure_markets_loaded", _noop_async)
    monkeypatch.setattr(
        service,
        "_Exchange__resolve_symbol_with_refresh",
        _resolved_symbol,
    )
    return service


@pytest.mark.asyncio
async def test_lookup_by_client_identity_returns_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, client = _exchange_with_lookup(
        monkeypatch,
        {"id": "exchange-order-1", "status": "closed"},
    )

    result = await service.lookup_spot_order(
        "BTCUSDC",
        {},
        client_order_id="mw-client-1",
    )

    assert result.status == ExchangeOrderLookupStatus.FOUND
    assert result.order == {"id": "exchange-order-1", "status": "closed"}
    assert client.calls == [
        (
            "mw-client-1",
            "BTC/USDC",
            {"clientOrderId": "mw-client-1"},
        )
    ]


@pytest.mark.asyncio
async def test_lookup_distinguishes_confirmed_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _client = _exchange_with_lookup(
        monkeypatch,
        ccxt.OrderNotFound("missing"),
    )

    result = await service.lookup_spot_order(
        "BTC/USDC",
        {},
        exchange_order_id="exchange-order-2",
    )

    assert result.status == ExchangeOrderLookupStatus.NOT_FOUND
    assert result.order is None
    assert result.error_message == "missing"


@pytest.mark.asyncio
async def test_lookup_distinguishes_exchange_unavailability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _client = _exchange_with_lookup(
        monkeypatch,
        ccxt.NetworkError("network down"),
    )

    result = await service.lookup_spot_order(
        "BTC/USDC",
        {},
        client_order_id="mw-client-3",
    )

    assert result.status == ExchangeOrderLookupStatus.UNAVAILABLE
    assert result.order is None
    assert result.error_message == "network down"


@pytest.mark.asyncio
@pytest.mark.parametrize("exchange_id", ["bybit", "bybiteu"])
async def test_bybit_lookup_uses_native_order_link_id_across_order_lists(
    monkeypatch: pytest.MonkeyPatch,
    exchange_id: str,
) -> None:
    client = _BybitLookupExchange(
        closed_orders=[
            {
                "id": "exchange-order-4",
                "status": "closed",
                "info": {"orderLinkId": "mw-client-4"},
            }
        ]
    )
    service = _exchange_with_client(monkeypatch, client)

    result = await service.lookup_spot_order(
        "BTCUSDC",
        {"exchange": exchange_id, "market": "spot"},
        client_order_id="mw-client-4",
    )

    assert result.status == ExchangeOrderLookupStatus.FOUND
    assert result.order is not None
    assert result.order["id"] == "exchange-order-4"
    assert client.calls == [
        ("open", "BTC/USDC", {"orderLinkId": "mw-client-4"}),
        ("closed", "BTC/USDC", {"orderLinkId": "mw-client-4"}),
    ]


@pytest.mark.asyncio
async def test_bybit_lookup_reports_unavailable_when_any_history_query_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _BybitLookupExchange(open_orders=ccxt.NetworkError("network down"))
    service = _exchange_with_client(monkeypatch, client)

    result = await service.lookup_spot_order(
        "BTCUSDC",
        {"exchange": "bybiteu", "market": "spot"},
        client_order_id="mw-client-5",
    )

    assert result.status == ExchangeOrderLookupStatus.UNAVAILABLE
    assert result.order is None
    assert result.error_message == "network down"


@pytest.mark.asyncio
async def test_bybit_lookup_reports_confirmed_absence_after_all_order_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _BybitLookupExchange(
        open_orders=[{"id": "other-open"}],
        closed_orders=[{"id": "other-closed"}],
        canceled_orders=[{"id": "other-canceled"}],
    )
    service = _exchange_with_client(monkeypatch, client)

    result = await service.lookup_spot_order(
        "BTCUSDC",
        {"exchange": "bybit", "market": "spot"},
        client_order_id="missing-client",
    )

    assert result.status == ExchangeOrderLookupStatus.NOT_FOUND
    assert result.order is None
    assert [call[0] for call in client.calls] == ["open", "closed", "canceled"]


@pytest.mark.asyncio
async def test_bybit_lookup_matches_public_client_order_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _BybitLookupExchange(
        open_orders=[
            {
                "id": "exchange-order-public",
                "clientOrderId": "public-client-id",
                "info": {},
            }
        ]
    )
    service = _exchange_with_client(monkeypatch, client)

    result = await service.lookup_spot_order(
        "BTCUSDC",
        {"exchange": "bybiteu", "market": "spot"},
        client_order_id="public-client-id",
    )

    assert result.status == ExchangeOrderLookupStatus.FOUND
    assert result.order is not None
    assert result.order["id"] == "exchange-order-public"


def test_bybit_fill_uses_look_up_cost_when_create_order_cost_is_none() -> None:
    """Regression for "ordersize is non nullable field, but null was passed".

    Bybit's create_order returns a bare async acknowledgment with cost=None; the
    real notional only appears on the looked-up fill. build_parsed_order_status
    must source ordersize from the fill, otherwise a None reaches the NOT NULL
    Trades.ordersize column and Tortoise rejects the insert.
    """
    bybit_ack = {
        "id": "2288831934878872832",
        "symbol": "BTC/USDC",
        "side": "buy",
        "type": "market",
        "cost": None,
        "amount": None,
        "price": None,
        "status": None,
        "timestamp": None,
        "filled": None,
        "average": None,
        "info": {
            "orderId": "2288831934878872832",
            "orderLinkId": "mw-bb65d20d565c8019bdc8f5c94fe2",
        },
        "trades": [],
    }
    fill = {
        "timestamp": 1756124430000,
        "amount": 0.000149,
        "total_amount": 0.000149,
        "price": "79504.6",
        "order": "2288831934878872832",
        "symbol": "BTC/USDC",
        "side": "buy",
        "fee_cost": 0.0,
        "base_fee": 0.0,
        "cost": 11.8461854,
    }

    parsed = build_parsed_order_status(bybit_ack, fill)

    assert parsed["ordersize"] is not None
    assert isinstance(parsed["ordersize"], float)
    assert parsed["ordersize"] == pytest.approx(11.8461854)
    assert parsed["amount"] == pytest.approx(0.000149)


def test_fallback_status_coerces_missing_cost_to_zero() -> None:
    """With no fill available, ordersize falls back to the create_order cost,
    coerced to 0.0 when the exchange returns a null cost (bybit bare ack)."""
    order = {
        "id": "2288831934878872832",
        "symbol": "BTC/USDC",
        "side": "buy",
        "type": "market",
        "cost": None,
        "amount": 0.0,
        "price": 0.0,
        "timestamp": 0,
        "fee": 0.0,
    }

    parsed = build_parsed_order_status(order, None)

    assert parsed["ordersize"] is not None
    assert parsed["ordersize"] == 0.0


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_shared_report_keeps_partial_execution_distinct_from_request(side):
    from service.accumulation_fill import AccumulationFill
    from service.exchange_types import ExchangeOrderReport

    order = {
        "id": "partial-1",
        "symbol": "BTC/USDC",
        "side": side,
        "status": "canceled",
        "timestamp": 1000,
        "amount": "1",
        "filled": "0.400000000000000001",
        "cost": "40.0000000000000001",
        "price": "100",
        "fees": [{"currency": "BTC", "cost": "0.000000000000000001"}],
    }
    report = ExchangeOrderReport.from_order(order)
    legacy = AccumulationFill.from_order(order)
    assert isinstance(legacy, ExchangeOrderReport)
    assert report.requested_quantity == "1"
    assert report.filled == legacy.filled == "0.400000000000000001"
    assert report.quote_cost == legacy.quote_cost == "40.0000000000000001"
    assert report.fees == legacy.fees == {"BTC": "0.000000000000000001"}
    parsed = build_parsed_order_status(order, None)
    assert parsed["amount"] == pytest.approx(0.4)
    assert parsed["total_amount"] == pytest.approx(0.4)


def test_requested_amount_in_acknowledgement_is_not_execution_evidence():
    order = {
        "id": "ack-only",
        "symbol": "BTC/USDC",
        "side": "buy",
        "timestamp": 1000,
        "amount": "1",
        "price": "100",
        "cost": None,
    }
    parsed = build_parsed_order_status(order, None)
    assert parsed["amount"] == 0
    assert parsed["total_amount"] == 0


def test_shared_execution_report_preserves_currencies_and_missing_fee_evidence():
    from service.exchange_types import ExchangeOrderReport

    order = {
        "id": "fill-1",
        "symbol": "BTC/USDC",
        "side": "buy",
        "status": "closed",
        "timestamp": 1000,
        "filled": "0.1",
        "cost": "10",
        "fees": [],
    }
    report = ExchangeOrderReport.from_order(order)
    assert not report.fees_complete
    assert report.requested_quantity is None
    report = ExchangeOrderReport.from_order(
        {
            **order,
            "fees": [
                {"currency": "BTC", "cost": "0.0001"},
                {"currency": "USDC", "cost": "0.01"},
                {"currency": "BNB", "cost": "0.001"},
            ],
        }
    )
    assert report.fees_complete
    assert report.fees == {"BTC": "0.0001", "USDC": "0.01", "BNB": "0.001"}

    zero = ExchangeOrderReport.from_order(
        {**order, "fee": {"cost": 0, "currency": None}}
    )
    assert zero.fees_complete and zero.fees == {}


def test_shared_private_fill_aggregation_keeps_exact_fees_and_rejects_duplicates():
    from service.exchange_helpers import aggregate_matched_trades

    fill = {
        "id": "fill-1",
        "order": "order-1",
        "symbol": "BTC/USDC",
        "side": "buy",
        "amount": "0.100000000000000001",
        "cost": "10.0000000000000001",
        "price": "100",
        "timestamp": 1000,
        "fee": {"currency": "BTC", "cost": "0.000000000000000001"},
    }
    aggregate = aggregate_matched_trades([fill, {**fill, "id": "fill-2"}], "BTC/USDC")
    report = aggregate["execution_report"]
    assert report.filled == "0.200000000000000002"
    assert report.quote_cost == "20.0000000000000002"
    assert report.fees == {"BTC": "0.000000000000000002"}
    with pytest.raises(ValueError, match="Duplicate execution identity"):
        aggregate_matched_trades([fill, fill], "BTC/USDC")
    with pytest.raises(ValueError, match="execution identity"):
        aggregate_matched_trades([{**fill, "id": None}], "BTC/USDC")
