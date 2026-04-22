import json

import pytest
import service.orders as orders_module
from service.orders import Orders


@pytest.mark.asyncio
async def test_receive_buy_order_retries_baseline_after_entry_sizing_failure(
    monkeypatch,
) -> None:
    orders = Orders()
    attempts: list[dict] = []
    persisted: list[tuple[str, dict, bool]] = []
    notifications: list[tuple[str, dict]] = []

    async def fake_create_spot_market_buy(order, _config):
        attempts.append(dict(order))
        if len(attempts) == 1:
            orders.exchange._last_buy_precheck_result = {
                "ok": False,
                "reason": "invalid_price_or_amount",
                "required_quote": 115.0,
                "available_quote": None,
            }
            return None
        return {
            **order,
            "timestamp": "1739400000000",
            "fees": 0.001,
            "precision": 8,
            "amount_fee": 0.0,
            "amount": 0.001,
            "price": 25000.0,
            "symbol": "BTC/USDT",
            "orderid": "buy-1",
        }

    async def fake_close() -> None:
        return None

    async def fake_persist_buy_trade(symbol, payload, *, create_open_trade):
        persisted.append((symbol, payload, create_open_trade))

    async def fake_notify(event_type, payload, _config):
        notifications.append((event_type, payload))

    async def fake_reset_unsellable_state(_symbol: str) -> None:
        return None

    monkeypatch.setattr(
        orders.exchange,
        "create_spot_market_buy",
        fake_create_spot_market_buy,
    )
    monkeypatch.setattr(orders.exchange, "close", fake_close)
    monkeypatch.setattr(orders_module, "persist_buy_trade", fake_persist_buy_trade)
    monkeypatch.setattr(orders.monitoring, "notify_trade", fake_notify)
    monkeypatch.setattr(orders, "_reset_unsellable_state", fake_reset_unsellable_state)

    result = await orders.receive_buy_order(
        {
            "ordersize": 115.0,
            "symbol": "BTC/USDT",
            "direction": "long",
            "botname": "asap_BTC/USDT",
            "baseorder": True,
            "safetyorder": False,
            "order_count": 0,
            "ordertype": "market",
            "so_percentage": None,
            "side": "buy",
            "signal_name": "asap",
            "strategy_name": "ema_cross",
            "timeframe": "15m",
            "metadata_json": json.dumps(
                {
                    "entry_sizing": {
                        "configured": True,
                        "applied": True,
                        "reason_code": "quick_profitable_closes",
                        "memory_status": "fresh",
                        "trust_direction": "favored",
                        "trust_score": 72.0,
                        "baseline_order_size": 100.0,
                        "suggested_order_size": 115.0,
                        "resolved_order_size": 115.0,
                    }
                },
                sort_keys=True,
            ),
            "baseline_order_size": 100.0,
            "entry_size_applied": True,
            "entry_size_reason_code": "quick_profitable_closes",
            "entry_size_fallback_applied": False,
            "entry_size_fallback_reason": None,
        },
        {"monitoring_enabled": True},
    )

    assert result is True
    assert [attempt["ordersize"] for attempt in attempts] == [115.0, 100.0]
    assert len(persisted) == 1
    assert persisted[0][0] == "BTC/USDT"
    assert persisted[0][2] is True
    metadata = json.loads(persisted[0][1]["metadata_json"])
    assert metadata["entry_sizing"]["applied"] is False
    assert metadata["entry_sizing"]["fallback_applied"] is True
    assert metadata["entry_sizing"]["fallback_reason_code"] == "invalid_price_or_amount"
    assert metadata["entry_sizing"]["resolved_order_size"] == 100.0
    assert persisted[0][1]["signal_name"] == "asap"
    assert len(notifications) == 1
