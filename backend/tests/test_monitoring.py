import os

import pytest
from service.monitoring import MonitoringService
from service.orders import Orders
from tortoise import Tortoise


@pytest.mark.asyncio
async def test_monitoring_service_skips_when_disabled(monkeypatch):
    service = MonitoringService()
    calls = []

    def fake_post_webhook(url, message, timeout_seconds):
        calls.append((url, message, timeout_seconds))

    monkeypatch.setattr(service, "_post_webhook", fake_post_webhook)

    await service.notify_trade(
        "trade.buy",
        {"symbol": "BTC/USDT"},
        {"monitoring_enabled": False, "monitoring_webhook_url": "http://example.com"},
    )

    assert calls == []


@pytest.mark.asyncio
async def test_monitoring_service_posts_webhook_when_enabled(monkeypatch):
    service = MonitoringService()
    calls = []

    def fake_post_webhook(url, message, timeout_seconds):
        calls.append((url, message, timeout_seconds))

    monkeypatch.setattr(service, "_post_webhook", fake_post_webhook)

    await service.notify_trade(
        "trade.sell",
        {"symbol": "ETH/USDT", "profit": 12.5},
        {
            "monitoring_enabled": True,
            "monitoring_channel": "webhook",
            "monitoring_webhook_url": "http://example.com/webhook",
            "monitoring_timeout_sec": 3,
            "monitoring_retry_count": 0,
            "exchange": "binance",
            "dry_run": True,
        },
    )

    assert len(calls) == 1
    sent_url, sent_message, sent_timeout = calls[0]
    assert sent_url == "http://example.com/webhook"
    assert sent_timeout == 3
    assert sent_message["event"] == "trade.sell"
    assert sent_message["trade"]["symbol"] == "ETH/USDT"


@pytest.mark.asyncio
async def test_monitoring_test_notification_sends_when_disabled(monkeypatch):
    service = MonitoringService()
    calls = []

    def fake_post_webhook(url, message, timeout_seconds):
        calls.append((url, message, timeout_seconds))

    monkeypatch.setattr(service, "_post_webhook", fake_post_webhook)

    success, _ = await service.send_test_notification(
        {
            "monitoring_enabled": False,
            "monitoring_channel": "webhook",
            "monitoring_webhook_url": "http://example.com/webhook",
            "monitoring_timeout_sec": 3,
            "monitoring_retry_count": 0,
        },
    )

    assert success is True
    assert len(calls) == 1
    assert calls[0][1]["event"] == "monitoring.test"


@pytest.mark.asyncio
async def test_monitoring_test_notification_requires_webhook_url():
    service = MonitoringService()
    success, _ = await service.send_test_notification(
        {
            "monitoring_channel": "webhook",
            "monitoring_webhook_url": "",
            "monitoring_timeout_sec": 3,
            "monitoring_retry_count": 0,
        },
    )

    assert success is False


@pytest.mark.asyncio
async def test_orders_buy_triggers_monitoring_notification(tmp_path, monkeypatch):
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    try:
        orders = Orders()
        notify_calls = []

        async def fake_create_spot_market_buy(_order, _config):
            return {
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

        async def fake_close():
            return None

        async def fake_notify(event_type, payload, _config):
            notify_calls.append((event_type, payload))

        monkeypatch.setattr(
            orders.exchange, "create_spot_market_buy", fake_create_spot_market_buy
        )
        monkeypatch.setattr(orders.exchange, "close", fake_close)
        monkeypatch.setattr(orders.monitoring, "notify_trade", fake_notify)

        result = await orders.receive_buy_order(
            {
                "ordersize": 25.0,
                "symbol": "BTC/USDT",
                "direction": "long",
                "botname": "asap_BTC/USDT",
                "baseorder": True,
                "safetyorder": False,
                "order_count": 0,
                "ordertype": "market",
                "so_percentage": None,
                "side": "buy",
            },
            {"monitoring_enabled": True},
        )

        assert result is True
        assert len(notify_calls) == 1
        assert notify_calls[0][0] == "trade.buy"
        assert notify_calls[0][1]["symbol"] == "BTC/USDT"
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_orders_sell_triggers_monitoring_notification(tmp_path, monkeypatch):
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    try:
        orders = Orders()
        notify_calls = []

        async def fake_create_spot_sell(_order, _config):
            return {
                "symbol": "BTC/USDT",
                "profit": 5.0,
                "profit_percent": 2.0,
                "total_amount": 0.001,
                "total_cost": 24000.0,
                "tp_price": 24500.0,
                "avg_price": 24000.0,
            }

        async def fake_get_token_amount_from_trades(_symbol):
            return 0.001

        async def fake_get_trade_by_ordertype(_symbol, baseorder=False):
            if baseorder:
                return [{"timestamp": "1739400000000"}]
            return []

        async def fake_get_open_trades_by_symbol(_symbol):
            return [{"so_count": 1}]

        async def fake_close():
            return None

        async def fake_notify(event_type, payload, _config):
            notify_calls.append((event_type, payload))

        monkeypatch.setattr(orders.exchange, "create_spot_sell", fake_create_spot_sell)
        monkeypatch.setattr(orders.exchange, "close", fake_close)
        monkeypatch.setattr(
            orders.trades,
            "get_token_amount_from_trades",
            fake_get_token_amount_from_trades,
        )
        monkeypatch.setattr(
            orders.trades, "get_trade_by_ordertype", fake_get_trade_by_ordertype
        )
        monkeypatch.setattr(
            orders.trades, "get_open_trades_by_symbol", fake_get_open_trades_by_symbol
        )
        monkeypatch.setattr(orders.monitoring, "notify_trade", fake_notify)

        await orders.receive_sell_order(
            {
                "symbol": "BTC/USDT",
                "direction": "long",
                "side": "sell",
                "type_sell": "order_sell",
                "actual_pnl": 2.0,
                "total_cost": 24000.0,
                "current_price": 24500.0,
            },
            {"monitoring_enabled": True},
        )

        assert len(notify_calls) == 1
        assert notify_calls[0][0] == "trade.sell"
        assert notify_calls[0][1]["symbol"] == "BTC/USDT"
        assert notify_calls[0][1]["so_count"] == 1
    finally:
        await Tortoise.close_connections()
