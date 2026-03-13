"""Tests for exchange risk helper utilities."""

from service.exchange_risk import (
    build_buy_precheck_result,
    get_min_notional_for_market,
    is_notional_below_minimum,
    normalize_buy_buffer_pct,
    resolve_required_buy_quote,
)


def test_get_min_notional_for_market_prefers_highest_applicable_value() -> None:
    market = {
        "limits": {"cost": {"min": "10"}},
        "info": {
            "filters": [
                {"filterType": "MIN_NOTIONAL", "minNotional": "12"},
                {"filterType": "NOTIONAL", "minNotional": "15"},
            ]
        },
    }

    assert get_min_notional_for_market(market, is_market_order=True) == 15.0


def test_get_min_notional_for_market_respects_market_flags() -> None:
    market = {
        "info": {
            "filters": [
                {
                    "filterType": "MIN_NOTIONAL",
                    "minNotional": "20",
                    "applyToMarket": "false",
                }
            ]
        }
    }

    assert get_min_notional_for_market(market, is_market_order=True) is None
    assert get_min_notional_for_market(market, is_market_order=False) == 20.0


def test_is_notional_below_minimum_reports_estimate() -> None:
    below, minimum, estimated = is_notional_below_minimum(2.0, 3.0, 10.0)

    assert below is True
    assert minimum == 10.0
    assert estimated == 6.0


def test_resolve_required_buy_quote_uses_larger_of_order_fields() -> None:
    order = {
        "ordersize": "100",
        "amount": "2",
        "price": "60",
    }

    assert resolve_required_buy_quote(order) == 120.0


def test_normalize_buy_buffer_pct_clamps_invalid_values() -> None:
    assert normalize_buy_buffer_pct("0.05") == 0.05
    assert normalize_buy_buffer_pct(None) == 0.0
    assert normalize_buy_buffer_pct(-1) == 0.0


def test_build_buy_precheck_result_rounds_numeric_fields() -> None:
    result = build_buy_precheck_result(
        ok=False,
        reason="insufficient_quote_balance",
        symbol="BTC/USDT",
        required_quote=123.123456789,
        available_quote=100.987654321,
        buffer_pct=0.01234567,
    )

    assert result == {
        "ok": False,
        "reason": "insufficient_quote_balance",
        "symbol": "BTC/USDT",
        "required_quote": 123.12345679,
        "available_quote": 100.98765432,
        "buffer_pct": 0.012346,
    }
