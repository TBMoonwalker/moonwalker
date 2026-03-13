"""Tests for exchange sell status helper utilities."""

from service.exchange_sell_status import (
    build_partial_sell_status,
    combine_partial_sell_statuses,
    finalize_sell_order_status,
    merge_partial_fill_with_market_sell,
)


def test_build_partial_sell_status_shapes_payload() -> None:
    status = build_partial_sell_status(
        symbol="BTC/USDT",
        partial_amount=1.5,
        partial_avg_price=105.0,
        remaining_amount=0.25,
        unsellable=True,
        unsellable_reason="minimum_notional",
        unsellable_min_notional=10.0,
        unsellable_estimated_notional=8.5,
    )

    assert status == {
        "type": "partial_sell",
        "symbol": "BTC/USDT",
        "partial_filled_amount": 1.5,
        "partial_avg_price": 105.0,
        "partial_proceeds": 157.5,
        "remaining_amount": 0.25,
        "unsellable": True,
        "unsellable_reason": "minimum_notional",
        "unsellable_min_notional": 10.0,
        "unsellable_estimated_notional": 8.5,
    }


def test_finalize_sell_order_status_adds_profit_metrics() -> None:
    finalized = finalize_sell_order_status(
        {
            "total_amount": 2.0,
            "price": 120.0,
            "symbol": "BTC/USDT",
        },
        total_cost=200.0,
        actual_pnl=19.5,
    )

    assert finalized["type"] == "sold_check"
    assert finalized["sell"] is True
    assert finalized["avg_price"] == 100.0
    assert finalized["tp_price"] == 120.0
    assert finalized["profit"] == 40.0
    assert finalized["profit_percent"] == 20.0
    assert finalized["actual_pnl"] == 19.5


def test_combine_partial_sell_statuses_merges_amounts_and_flags() -> None:
    combined = combine_partial_sell_statuses(
        symbol="BTC/USDT",
        first_partial_amount=1.0,
        first_partial_price=100.0,
        second_status={
            "partial_filled_amount": 0.5,
            "partial_avg_price": 120.0,
            "remaining_amount": 0.25,
            "unsellable": True,
            "unsellable_reason": "minimum_notional",
            "unsellable_min_notional": 15.0,
            "unsellable_estimated_notional": 12.0,
        },
    )

    assert combined["partial_filled_amount"] == 1.5
    assert combined["partial_avg_price"] == 106.66666666666667
    assert combined["remaining_amount"] == 0.25
    assert combined["unsellable"] is True


def test_merge_partial_fill_with_market_sell_updates_market_status() -> None:
    merged = merge_partial_fill_with_market_sell(
        {
            "type": "sold_check",
            "total_amount": 1.0,
            "price": 130.0,
        },
        partial_amount=1.0,
        partial_price=110.0,
        total_cost=200.0,
    )

    assert merged["total_amount"] == 2.0
    assert merged["price"] == 120.0
    assert merged["tp_price"] == 120.0
    assert merged["avg_price"] == 100.0
    assert merged["profit"] == 40.0
    assert merged["profit_percent"] == 20.0
