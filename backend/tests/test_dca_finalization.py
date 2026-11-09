"""Leaf unit tests for the pure helpers in service/dca/finalization.py.

Value: protects=entry-size retry reasons and retry payload, TP-limit
    fallback pricing and payload shape, and closed-trade partial arithmetic
    including zero partials.
fails_when=the retry reason set, fallback pricing, or partial totals change.
why_new=indirect full-flow coverage only; these helpers had no unit tests.
seam=none (collaborators are fakes; no exchange or database access).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import helper
import pytest
from service.dca import finalization
from service.dca.finalization import (
    build_entry_size_retry_order,
    build_tp_limit_sell_payload,
)


@dataclass(frozen=True)
class _UnusedCollaborator:
    """Placeholder collaborator for context fields a helper never touches."""


def _dependencies(*, trades: Any = None, utils: Any = None) -> Any:
    """Build a finalization context with real utils and inert collaborators."""
    return finalization.DcaFinalizationContext(
        trades=trades or _UnusedCollaborator(),
        monitoring=_UnusedCollaborator(),
        placement_workflow=_UnusedCollaborator(),
        exchange=_UnusedCollaborator(),
        utils=utils or helper.Utils(),
    )


@pytest.mark.parametrize(
    "reason",
    sorted(finalization.ENTRY_SIZING_RETRY_REASONS),
)
def test_entry_size_retry_builds_baseline_order_for_each_fallback_reason(
    reason: str,
) -> None:
    order = {
        "baseorder": True,
        "safetyorder": False,
        "ordersize": 115.0,
        "baseline_order_size": 100.0,
        "entry_size_applied": True,
        "metadata_json": json.dumps({"entry_sizing": {"applied": True}}),
    }
    original = json.loads(json.dumps(order))

    retry = build_entry_size_retry_order(order, {"ok": False, "reason": reason})

    assert retry is not None
    assert retry["ordersize"] == 100.0
    assert retry["entry_size_applied"] is False
    assert retry["entry_size_fallback_applied"] is True
    assert retry["entry_size_fallback_reason"] == reason
    metadata = json.loads(retry["metadata_json"])
    assert metadata["entry_sizing"]["applied"] is False
    assert metadata["entry_sizing"]["fallback_applied"] is True
    assert metadata["entry_sizing"]["fallback_reason_code"] == reason
    assert metadata["entry_sizing"]["resolved_order_size"] == 100.0
    assert order == original, "retry must not mutate the incoming order"


@pytest.mark.parametrize(
    "order",
    [
        # Only base orders carry entry sizing.
        {
            "safetyorder": True,
            "ordersize": 115.0,
            "baseline_order_size": 100.0,
            "entry_size_applied": True,
        },
        # Entry sizing never applied, nothing to fall back.
        {"baseorder": True, "ordersize": 115.0, "baseline_order_size": 100.0},
        # Sizing applied but already at the baseline.
        {
            "baseorder": True,
            "ordersize": 100.0,
            "baseline_order_size": 100.0,
            "entry_size_applied": True,
        },
    ],
)
def test_entry_size_retry_gives_up_outside_the_contract(
    order: dict[str, Any],
) -> None:
    assert (
        build_entry_size_retry_order(
            order, {"ok": False, "reason": "invalid_price_or_amount"}
        )
        is None
    )
    assert build_entry_size_retry_order(order, None) is None


def test_entry_size_retry_rejects_unknown_fallback_reasons() -> None:
    order = {
        "baseorder": True,
        "ordersize": 115.0,
        "baseline_order_size": 100.0,
        "entry_size_applied": True,
    }
    assert build_entry_size_retry_order(order, {"ok": False, "reason": ""}) is None
    assert (
        build_entry_size_retry_order(order, {"ok": False, "reason": "unknown"}) is None
    )
    assert build_entry_size_retry_order(order, {"ok": True}) is None


def test_tp_limit_sell_payload_falls_back_to_trade_pricing() -> None:
    trades = {
        "symbol": "BTC/USDC",
        "tp_limit_order_id": "tp-1",
        "tp_limit_order_price": 110.0,
        "tp_limit_order_amount": 2.0,
        "sellable_amount": 2.5,
        "total_cost": 200.0,
        "total_amount": 2.5,
        "fee": 0.0,
        "current_price": 105.0,
    }
    # No exchange price evidence: price and amount must come from the trade.
    payload = build_tp_limit_sell_payload(
        trades, {"timestamp": 1700000000000}, dependencies=_dependencies()
    )

    assert payload["id"] == "tp-1"
    assert payload["symbol"] == "BTC/USDC"
    assert payload["side"] == "sell"
    assert payload["ordertype"] == "limit"
    assert payload["price"] == 110.0
    assert payload["amount"] == 2.0
    assert payload["total_amount"] == 2.0
    assert payload["requested_total_amount"] == 2.5
    assert payload["cost"] == 220.0
    assert payload["fee"] == 0.0
    assert payload["total_cost"] == 200.0
    # average buy 200 / 2.5 = 80 -> (110 - 80) / 80
    assert payload["actual_pnl"] == pytest.approx(37.5)


def test_tp_limit_sell_payload_prefers_exchange_evidence() -> None:
    trades = {
        "symbol": "BTC/USDC",
        "tp_limit_order_id": "tp-1",
        "tp_limit_order_price": 110.0,
        "tp_limit_order_amount": 2.0,
        "sellable_amount": 2.5,
        "total_cost": 200.0,
        "total_amount": 2.5,
        "fee": 0.0,
        "current_price": 105.0,
    }
    payload = build_tp_limit_sell_payload(
        trades,
        {"id": "exchange-tp", "average": 111.0, "filled": 1.5, "fee": 0.05},
        dependencies=_dependencies(),
    )

    assert payload["id"] == "exchange-tp"
    assert payload["price"] == 111.0
    assert payload["amount"] == 1.5
    assert payload["cost"] == pytest.approx(1.5 * 111.0)
    assert payload["fee"] == 0.05


class _StatsTradeReader:
    """Fake trade reader that refuses the second partial-total read."""

    def __init__(self) -> None:
        self.partial_reads = 0

    async def get_trade_by_ordertype(self, _symbol: str, **_kwargs: Any) -> Any:
        return [{"timestamp": 1700000000000.0}]

    async def get_open_trades_by_symbol(self, _symbol: str) -> Any:
        return [{"so_count": 2}]

    async def get_partial_sell_execution(self, *_args: Any, **_kwargs: Any) -> Any:
        self.partial_reads += 1
        raise AssertionError("supplied partial totals must not trigger a second read")


@pytest.mark.asyncio
async def test_closed_trade_stats_uses_supplied_partial_totals() -> None:
    trades = _StatsTradeReader()
    order_status: dict[str, Any] = {
        "symbol": "BTC/USDC",
        "total_cost": 200.0,
        "total_amount": 1.0,
        "price": 120.0,
        "timestamp": 1700000100000,
        "close_reason": "take_profit",
    }

    result = await finalization.calculate_closed_trade_stats(
        order_status,
        dependencies=_dependencies(trades=trades),
        partial_amount=0.5,
        partial_proceeds=60.0,
    )

    payload = result["payload"]
    assert trades.partial_reads == 0
    # 0.5 @ 60 + 1.0 @ 120 = 180 over 1.5 for a 200 cost basis.
    assert payload["amount"] == pytest.approx(1.5)
    assert payload["tp_price"] == pytest.approx(120.0)
    assert payload["avg_price"] == pytest.approx(200.0 / 1.5)
    assert payload["profit"] == pytest.approx(-20.0)
    assert payload["profit_percent"] == pytest.approx(-10.0)
    assert result["monitor_payload"]["amount"] == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_closed_trade_stats_zero_partials_close_on_final_fill_only() -> None:
    trades = _StatsTradeReader()
    order_status: dict[str, Any] = {
        "symbol": "BTC/USDC",
        "total_cost": 200.0,
        "total_amount": 1.0,
        "price": 120.0,
        "timestamp": 1700000100000,
        "close_reason": "manual_stop",
    }

    result = await finalization.calculate_closed_trade_stats(
        order_status,
        dependencies=_dependencies(trades=trades),
        partial_amount=0.0,
        partial_proceeds=0.0,
    )

    payload = result["payload"]
    assert trades.partial_reads == 0
    assert payload["amount"] == pytest.approx(1.0)
    assert payload["tp_price"] == pytest.approx(120.0)
    assert payload["avg_price"] == pytest.approx(200.0)
    assert payload["profit"] == pytest.approx(-80.0)
    assert payload["profit_percent"] == pytest.approx(-40.0)
