"""Regression coverage for extracted exchange order lookup helpers."""

import pytest
from service.exchange_order_lookup import (
    build_parsed_order_status,
    lookup_aggregated_trade,
)


class _DummyLogger:
    def debug(self, *_args, **_kwargs) -> None:
        pass


class _TradeLookupExchange:
    def milliseconds(self) -> int:
        return 2_000_000

    async def fetch_order_trades(
        self, _orderid: str, _symbol: str
    ) -> list[dict[str, object]]:
        return [
            {
                "order": "abc123",
                "amount": 1.2,
                "cost": 120.0,
                "fee": {"cost": 0.2, "currency": "USDT"},
                "timestamp": 1_999_000,
                "price": 100.0,
                "symbol": "BTC/USDT",
                "side": "buy",
            }
        ]


@pytest.mark.asyncio
async def test_lookup_aggregated_trade_returns_trade_payload() -> None:
    trade = await lookup_aggregated_trade(
        _TradeLookupExchange(),
        logger=_DummyLogger(),
        symbol="BTC/USDT",
        orderid="abc123",
        order_check_range_seconds=300,
        order_timestamp=1_998_000,
    )

    assert trade is not None
    assert trade["order"] == "abc123"
    assert trade["amount"] == pytest.approx(1.2)
    assert trade["fee_cost"] == pytest.approx(0.2)


def test_build_parsed_order_status_prefers_trade_payload() -> None:
    order = {
        "id": "abc123",
        "timestamp": 1_998_000,
        "amount": 1.0,
        "price": 95.0,
        "symbol": "BTC/USDT",
        "side": "buy",
        "fee": {"cost": 0.1, "currency": "USDT"},
        "cost": 95.0,
    }

    parsed = build_parsed_order_status(
        order,
        {
            "timestamp": 1_999_000,
            "amount": 1.2,
            "price": 100.0,
            "order": "abc123",
            "symbol": "BTC/USDT",
            "side": "buy",
            "fee_cost": 0.2,
            "base_fee": 0.0,
        },
    )

    assert parsed["timestamp"] == 1_999_000
    assert parsed["amount"] == pytest.approx(1.2)
    assert parsed["price"] == pytest.approx(100.0)
    assert parsed["ordersize"] == pytest.approx(95.0)


def test_build_parsed_order_status_falls_back_to_order_payload() -> None:
    order = {
        "id": "abc123",
        "timestamp": 1_998_000,
        "amount": 1.0,
        "price": 95.0,
        "symbol": "BTC/USDT",
        "side": "buy",
        "fee": {"cost": 0.1, "currency": "USDT"},
        "cost": 95.0,
    }

    parsed = build_parsed_order_status(order, None)

    assert parsed["timestamp"] == 1_998_000
    assert parsed["amount"] == pytest.approx(1.0)
    assert parsed["price"] == pytest.approx(95.0)
    assert parsed["amount_fee"] == {"cost": 0.1, "currency": "USDT"}
