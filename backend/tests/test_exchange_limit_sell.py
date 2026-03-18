"""Tests for limit sell helper utilities."""

from service.exchange_limit_sell import (
    build_market_fallback_status,
    build_partial_status_from_fallback,
    get_limit_sell_timeout_seconds,
)


def test_get_limit_sell_timeout_seconds_validates_values() -> None:
    assert get_limit_sell_timeout_seconds({"limit_sell_timeout_sec": 15}) == 15
    assert get_limit_sell_timeout_seconds({"limit_sell_timeout_sec": 0}) == 1
    assert get_limit_sell_timeout_seconds({"limit_sell_timeout_sec": "invalid"}) == 60


def test_build_market_fallback_status_shapes_result() -> None:
    status = build_market_fallback_status(
        symbol="BTC/USDT",
        remaining_amount=0.75,
        partial_filled_amount=0.25,
        partial_avg_price=110.0,
    )

    assert status == {
        "requires_market_fallback": True,
        "limit_cancel_confirmed": True,
        "fallback_reason": "limit_order_timeout",
        "symbol": "BTC/USDT",
        "remaining_amount": 0.75,
        "partial_filled_amount": 0.25,
        "partial_avg_price": 110.0,
    }


def test_build_partial_status_from_fallback_uses_default_symbol() -> None:
    partial = build_partial_status_from_fallback(
        {
            "remaining_amount": 0.5,
            "partial_filled_amount": 1.25,
            "partial_avg_price": 101.0,
        },
        default_symbol="ETH/USDT",
    )

    assert partial["symbol"] == "ETH/USDT"
    assert partial["partial_filled_amount"] == 1.25
    assert partial["partial_avg_price"] == 101.0
    assert partial["remaining_amount"] == 0.5
