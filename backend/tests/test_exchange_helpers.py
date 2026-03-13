"""Tests for exchange helper utilities."""

from service.exchange_helpers import (
    aggregate_matched_trades,
    extract_free_amount,
    is_matching_order_id,
    precision_step_for_amount,
    safe_float,
)


def test_is_matching_order_id_handles_mixed_types() -> None:
    assert is_matching_order_id(12345, "12345") is True
    assert is_matching_order_id("12345", "12345") is True
    assert is_matching_order_id(None, "12345") is False
    assert is_matching_order_id("other", "12345") is False


def test_aggregate_matched_trades_combines_partial_fills() -> None:
    matched_orders = [
        {
            "amount": 1.5,
            "cost": 150.0,
            "timestamp": 1000,
            "price": 100.0,
            "order": "abc",
            "symbol": "BTC/USDT",
            "side": "buy",
            "fee": {"cost": 0.01, "currency": "BTC"},
        },
        {
            "amount": 0.5,
            "cost": 55.0,
            "timestamp": 2000,
            "price": 110.0,
            "order": "abc",
            "symbol": "BTC/USDT",
            "side": "buy",
            "fee": {"cost": 1.0, "currency": "USDT"},
        },
    ]

    aggregated = aggregate_matched_trades(matched_orders, "BTC/USDT")

    assert aggregated["amount"] == 2.0
    assert aggregated["cost"] == 205.0
    assert aggregated["fee"] == 1.01
    assert aggregated["base_fee"] == 0.01
    assert aggregated["price"] == 102.5
    assert aggregated["timestamp"] == 2000
    assert aggregated["order"] == "abc"


def test_precision_step_for_amount_ignores_trailing_zeroes() -> None:
    assert precision_step_for_amount("12") == 1.0
    assert precision_step_for_amount("12.3400") == 0.01
    assert precision_step_for_amount("12.0000") == 1.0


def test_safe_float_returns_none_for_invalid_values() -> None:
    assert safe_float("12.5") == 12.5
    assert safe_float(None) is None
    assert safe_float("invalid") is None


def test_extract_free_amount_supports_nested_and_flat_balance_shapes() -> None:
    nested_balance = {"BTC": {"free": "0.5"}}
    flat_balance = {"free": {"USDT": "125.25"}}

    assert extract_free_amount(nested_balance, "BTC") == 0.5
    assert extract_free_amount(flat_balance, "USDT") == 125.25
    assert extract_free_amount({}, "ETH") is None
