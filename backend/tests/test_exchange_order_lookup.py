"""Tests for typed exchange-order reconciliation lookups."""

from __future__ import annotations

from typing import Any

import ccxt.async_support as ccxt
import pytest
from service.exchange import Exchange
from service.exchange_capabilities import ExchangeOrderLookupStatus


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
