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
