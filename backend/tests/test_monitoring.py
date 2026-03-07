import pytest
from service.monitoring import MonitoringService
from service.orders import Orders


@pytest.mark.asyncio
async def test_monitoring_service_skips_when_disabled(monkeypatch) -> None:
    service = MonitoringService()
    calls = []

    async def fake_send_telegram(api_id, api_hash, bot_token, chat_id, text) -> None:
        calls.append((api_id, api_hash, bot_token, chat_id, text))

    monkeypatch.setattr(service, "_send_telegram", fake_send_telegram)

    await service.notify_trade(
        "trade.buy",
        {"symbol": "BTC/USDT"},
        {
            "monitoring_enabled": False,
            "monitoring_telegram_api_id": 12345,
            "monitoring_telegram_api_hash": "hash123",
            "monitoring_telegram_bot_token": "token123",
            "monitoring_telegram_chat_id": "987654321",
        },
    )

    assert calls == []


@pytest.mark.asyncio
async def test_monitoring_service_sends_telegram_when_enabled(monkeypatch) -> None:
    service = MonitoringService()
    calls = []

    async def fake_send_telegram(api_id, api_hash, bot_token, chat_id, text) -> None:
        calls.append((api_id, api_hash, bot_token, chat_id, text))

    monkeypatch.setattr(service, "_send_telegram", fake_send_telegram)

    await service.notify_trade(
        "trade.buy",
        {"symbol": "BTC/USDT", "side": "buy"},
        {
            "monitoring_enabled": True,
            "monitoring_telegram_api_id": 12345,
            "monitoring_telegram_api_hash": "hash123",
            "monitoring_telegram_bot_token": "token123",
            "monitoring_telegram_chat_id": "987654321",
            "monitoring_retry_count": 0,
        },
    )

    assert len(calls) == 1
    sent_api_id, sent_api_hash, sent_token, sent_chat_id, sent_text = calls[0]
    assert sent_api_id == 12345
    assert sent_api_hash == "hash123"
    assert sent_token == "token123"
    assert sent_chat_id == "987654321"
    assert "Moonwalker trade.buy" in sent_text


@pytest.mark.asyncio
async def test_monitoring_test_notification_sends_when_disabled(monkeypatch) -> None:
    service = MonitoringService()
    calls = []

    async def fake_send_telegram(api_id, api_hash, bot_token, chat_id, text) -> None:
        calls.append((api_id, api_hash, bot_token, chat_id, text))

    monkeypatch.setattr(service, "_send_telegram", fake_send_telegram)

    success, _ = await service.send_test_notification(
        {
            "monitoring_enabled": False,
            "monitoring_telegram_api_id": 12345,
            "monitoring_telegram_api_hash": "hash123",
            "monitoring_telegram_bot_token": "token123",
            "monitoring_telegram_chat_id": "987654321",
            "monitoring_retry_count": 0,
        },
    )

    assert success is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_monitoring_service_fails_without_telegram_credentials() -> None:
    service = MonitoringService()
    success, _ = await service.send_test_notification(
        {
            "monitoring_telegram_api_id": 0,
            "monitoring_telegram_api_hash": "",
            "monitoring_telegram_bot_token": "",
            "monitoring_telegram_chat_id": "",
            "monitoring_retry_count": 0,
        },
    )

    assert success is False


def test_resolve_telegram_entity_numeric() -> None:
    service = MonitoringService()
    assert service._resolve_telegram_entity("-1001234567890") == -1001234567890


def test_resolve_telegram_entity_username() -> None:
    service = MonitoringService()
    assert (
        service._resolve_telegram_entity("@moonwalker_channel") == "@moonwalker_channel"
    )


@pytest.mark.asyncio
async def test_orders_buy_triggers_monitoring_notification(monkeypatch) -> None:
    try:
        orders = Orders()
        notify_calls = []

        async def fake_run_sqlite(func, *args, **kwargs) -> None:
            return None

        monkeypatch.setattr(
            "service.orders.run_sqlite_write_with_retry", fake_run_sqlite
        )

        async def fake_create_spot_market_buy(_order, _config) -> None:
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

        async def fake_close() -> None:
            return None

        async def fake_notify(event_type, payload, _config) -> None:
            notify_calls.append((event_type, payload))

        async def fake_get_partial_sell_execution(_symbol) -> None:
            return 0.0, 0.0

        monkeypatch.setattr(
            orders.exchange, "create_spot_market_buy", fake_create_spot_market_buy
        )
        monkeypatch.setattr(orders.exchange, "close", fake_close)
        monkeypatch.setattr(
            orders.trades, "get_partial_sell_execution", fake_get_partial_sell_execution
        )
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
        pass


@pytest.mark.asyncio
async def test_orders_sell_triggers_monitoring_notification(monkeypatch) -> None:
    try:
        orders = Orders()
        notify_calls = []

        async def fake_run_sqlite(func, *args, **kwargs) -> None:
            return None

        monkeypatch.setattr(
            "service.orders.run_sqlite_write_with_retry", fake_run_sqlite
        )

        async def fake_create_spot_sell(_order, _config) -> None:
            return {
                "symbol": "BTC/USDT",
                "profit": 5.0,
                "profit_percent": 2.0,
                "total_amount": 0.001,
                "total_cost": 24000.0,
                "tp_price": 24500.0,
                "avg_price": 24000.0,
            }

        async def fake_get_token_amount_from_trades(_symbol) -> None:
            return 0.001

        async def fake_get_trade_by_ordertype(_symbol, baseorder=False) -> None:
            if baseorder:
                return [{"timestamp": "1739400000000"}]
            return []

        async def fake_get_open_trades_by_symbol(_symbol) -> None:
            return [{"so_count": 1}]

        async def fake_close() -> None:
            return None

        async def fake_notify(event_type, payload, _config) -> None:
            notify_calls.append((event_type, payload))

        async def fake_get_partial_sell_execution(_symbol) -> None:
            return 0.0, 0.0

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
        monkeypatch.setattr(
            orders.trades, "get_partial_sell_execution", fake_get_partial_sell_execution
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
        pass
