"""Binance-style order-only lookups require complete order-specific commission data."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from service.accumulation_fill import AccumulationFill
from service.accumulation_order_fees import hydrate_accumulation_order


def order():
    return {
        "id": "42",
        "symbol": "BTC/USDC",
        "side": "buy",
        "status": "closed",
        "filled": "0.3",
        "cost": "30",
        "timestamp": 1700000000000,
        "fee": None,
        "fees": [],
    }


def trades():
    return [
        {
            "id": str(i),
            "order": "42",
            "symbol": "BTC/USDC",
            "side": "buy",
            "amount": "0.1",
            "fee": {"currency": "BTC", "cost": "0.0001"},
        }
        for i in range(3)
    ]


@pytest.mark.asyncio
async def test_missing_order_commissions_are_hydrated_from_complete_authenticated_execution_coverage():
    exchange = SimpleNamespace(
        read_spot_order_executions=AsyncMock(return_value=trades())
    )
    original = order()
    hydrated = await hydrate_accumulation_order(
        exchange, original, {"exchange": "binance"}
    )
    report = AccumulationFill.from_order(hydrated)
    assert report.fees_complete and report.fees == {"BTC": "0.0003"}
    assert original["fee"] is None and original["fees"] == []
    assert (
        hydrated["filled"] == original["filled"]
        and hydrated["cost"] == original["cost"]
    )
    exchange.read_spot_order_executions.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "partial",
        "duplicate",
        "foreign_order",
        "foreign_symbol",
        "foreign_side",
        "missing_fee",
        "oversized",
        "failure",
    ],
)
async def test_incomplete_or_mismatched_execution_coverage_never_becomes_zero_fees(
    fault,
):
    evidence = trades()
    if fault == "partial":
        evidence.pop()
    elif fault == "duplicate":
        evidence[1]["id"] = evidence[0]["id"]
    elif fault == "foreign_order":
        evidence[0]["order"] = "43"
    elif fault == "foreign_symbol":
        evidence[0]["symbol"] = "ETH/USDC"
    elif fault == "foreign_side":
        evidence[0]["side"] = "sell"
    elif fault == "missing_fee":
        evidence[0]["fee"] = None
    elif fault == "oversized":
        evidence *= 334
    exchange = SimpleNamespace(
        read_spot_order_executions=AsyncMock(return_value=evidence)
    )
    if fault == "failure":
        exchange.read_spot_order_executions.side_effect = TimeoutError()
    original = order()
    assert await hydrate_accumulation_order(exchange, original, {}) == original
    assert not AccumulationFill.from_order(original).fees_complete
