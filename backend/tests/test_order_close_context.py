from datetime import datetime
from typing import cast

import pytest
from service.exchange_types import PartialSellStatus
from service.order_close_context import (
    build_unsellable_remainder_context,
    build_unsellable_status_snapshot,
)


def test_build_unsellable_status_snapshot_normalizes_values() -> None:
    snapshot = build_unsellable_status_snapshot(
        cast(
            PartialSellStatus,
            {
                "symbol": "LPT/USDC",
                "partial_filled_amount": -1.0,
                "partial_proceeds": "11.64288",
                "remaining_amount": "0.01",
                "unsellable_reason": None,
                "unsellable_min_notional": "10.0",
                "unsellable_estimated_notional": "0.02274",
            },
        )
    )

    assert snapshot.symbol == "LPT/USDC"
    assert snapshot.partial_amount == 0.0
    assert snapshot.partial_proceeds == pytest.approx(11.64288)
    assert snapshot.remaining_amount == pytest.approx(0.01)
    assert snapshot.reason == "minimum_notional"
    assert snapshot.min_notional == pytest.approx(10.0)
    assert snapshot.estimated_notional == pytest.approx(0.02274)


def test_build_unsellable_remainder_context_returns_close_and_archive_payloads() -> (
    None
):
    snapshot = build_unsellable_status_snapshot(
        {
            "symbol": "LPT/USDC",
            "partial_filled_amount": 5.12,
            "partial_proceeds": 11.64288,
            "remaining_amount": 0.01,
            "unsellable_reason": "minimum_notional",
            "unsellable_min_notional": 10.0,
            "unsellable_estimated_notional": 0.02274,
        }
    )

    context = build_unsellable_remainder_context(
        snapshot,
        open_trade={
            "amount": 5.13,
            "cost": 11.98,
            "current_price": 2.274,
            "open_date": "1773580000000",
            "unsellable_notice_sent": False,
        },
        so_count=0,
        open_timestamp_ms=1_773_580_000_000.0,
        closed_at=datetime(2026, 3, 14, 12, 0, 0),
        unsellable_since="2026-03-18T12:34:56",
    )

    assert context.already_notified is False
    assert context.closed_trade_payload is not None
    assert context.closed_trade_payload["symbol"] == "LPT/USDC"
    assert context.closed_trade_payload["open_date"] == "2026-03-15 13:06:40+00:00"
    assert context.closed_trade_payload["close_date"] == "2026-03-14 12:00:00+00:00"
    assert context.closed_trade_payload["amount"] == pytest.approx(5.12)
    assert context.closed_trade_payload["cost"] == pytest.approx(11.95664717)
    assert context.closed_trade_payload["tp_price"] == pytest.approx(2.274)
    assert context.unsellable_payload["amount"] == pytest.approx(0.01)
    assert context.unsellable_payload["cost"] == pytest.approx(0.02335283)
    assert context.unsellable_payload["current_price"] == pytest.approx(2.274)
    assert context.unsellable_payload["avg_price"] == pytest.approx(2.33528265)
    assert context.unsellable_payload["unsellable_since"] == "2026-03-18T12:34:56"
    assert context.monitor_payload["symbol"] == "LPT/USDC"
    assert context.monitor_payload["partial_filled_amount"] == pytest.approx(5.12)
    assert context.monitor_payload["remaining_amount"] == pytest.approx(0.01)


def test_build_unsellable_remainder_context_skips_close_payload_without_partial_fill() -> (
    None
):
    snapshot = build_unsellable_status_snapshot(
        {
            "symbol": "BTC/USDT",
            "partial_filled_amount": 0.0,
            "partial_proceeds": 0.0,
            "remaining_amount": 0.001,
            "unsellable_reason": "minimum_notional",
        }
    )

    context = build_unsellable_remainder_context(
        snapshot,
        open_trade=None,
        so_count=0,
        open_timestamp_ms=None,
        unsellable_since="2026-03-18T12:34:56",
    )

    assert context.closed_trade_payload is None
    assert context.unsellable_payload["amount"] == pytest.approx(0.001)
    assert context.unsellable_payload["cost"] == pytest.approx(0.0)
    assert context.unsellable_payload["avg_price"] == pytest.approx(0.0)
