from datetime import datetime

from service.order_payloads import (
    build_buy_monitor_payload,
    build_buy_trade_payload,
    build_closed_trade_payloads,
    build_manual_buy_open_trade_payload,
    build_manual_buy_trade_payload,
    calculate_trade_duration,
)


def test_calculate_trade_duration_returns_json_payload() -> None:
    duration = calculate_trade_duration(0, 90_000)

    assert duration == '{"days": 0, "hours": 0, "minutes": 1, "seconds": 30}'


def test_build_closed_trade_payloads_includes_partial_sell_proceeds() -> None:
    result = build_closed_trade_payloads(
        {
            "symbol": "BTC/USDC",
            "total_cost": 100.0,
            "total_amount": 1.0,
            "price": 120.0,
        },
        so_count=2,
        open_timestamp_ms=1_000.0,
        partial_amount=0.5,
        partial_proceeds=55.0,
        closed_at=datetime(2026, 3, 13, 12, 0, 0),
    )

    payload = result["payload"]
    monitor_payload = result["monitor_payload"]

    assert payload["amount"] == 1.5
    assert payload["cost"] == 100.0
    assert payload["tp_price"] == (55.0 + 120.0) / 1.5
    assert payload["profit"] == 75.0
    assert monitor_payload["amount"] == 1.5
    assert monitor_payload["so_count"] == 2


def test_build_manual_buy_payload_helpers_return_expected_values() -> None:
    trade_payload = build_manual_buy_trade_payload(
        normalized_symbol="BTC/USDC",
        timestamp_ms=3_000_000,
        price=80.0,
        amount=0.5,
        ordersize=40.0,
        amount_precision=1,
        order_count=2,
        so_percentage=-11.11,
        trade_data={"bot": "asap_BTC/USDC", "ordertype": "market", "direction": "long"},
    )
    open_trade_payload = build_manual_buy_open_trade_payload(
        open_trade={"so_count": 1, "amount": 1.0, "cost": 100.0},
        amount=0.5,
        ordersize=40.0,
        order_count=2,
        tp_percent=1.0,
    )

    assert trade_payload["symbol"] == "BTC/USDC"
    assert trade_payload["order_count"] == 2
    assert trade_payload["orderid"] == "manual-add-BTCUSDC-3000000-2"
    assert open_trade_payload["so_count"] == 2
    assert open_trade_payload["amount"] == 1.5
    assert open_trade_payload["cost"] == 140.0
    assert open_trade_payload["tp_price"] == (140.0 / 1.5) * 1.01


def test_build_buy_payload_helpers_return_expected_values() -> None:
    order_status = {
        "timestamp": "1739400000000",
        "ordersize": 25.0,
        "fees": 0.001,
        "precision": 8,
        "amount_fee": 0.0,
        "amount": 0.001,
        "price": 25000.0,
        "symbol": "BTC/USDT",
        "orderid": "buy-1",
        "botname": "asap_BTC/USDT",
        "ordertype": "market",
        "baseorder": True,
        "safetyorder": False,
        "order_count": 0,
        "so_percentage": None,
        "direction": "long",
        "side": "buy",
    }

    trade_payload = build_buy_trade_payload(order_status)
    monitor_payload = build_buy_monitor_payload(order_status)

    assert trade_payload["symbol"] == "BTC/USDT"
    assert trade_payload["bot"] == "asap_BTC/USDT"
    assert trade_payload["fee"] == 0.001
    assert trade_payload["direction"] == "long"
    assert monitor_payload["symbol"] == "BTC/USDT"
    assert monitor_payload["side"] == "buy"
    assert monitor_payload["ordertype"] == "market"
