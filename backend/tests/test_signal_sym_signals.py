import asyncio
import types

import model
import pytest
import signals.sym_signals as sym_module
from signals.sym_signals import SignalPlugin


class DummyTrades:
    @classmethod
    def all(cls):
        return cls()

    async def values_list(self, *args, **kwargs):
        return []

    def distinct(self):
        return self


@pytest.mark.asyncio
async def test_sym_signals_run_triggers_buy_order(monkeypatch):
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)

    monkeypatch.setattr(model, "Trades", DummyTrades)

    class DummyAsyncClient:
        def __init__(self):
            self.connected = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def connect(self, *_args, **_kwargs):
            self.connected = True

        async def receive(self, *_, **__):
            plugin.status = False
            return [
                "signal",
                {
                    "symbol": "BTC",
                    "signal": "BOT_START",
                    "signal_name_id": 1,
                    "market_cap_rank": 1,
                    "volume_24h": {"BINANCE": {"USDT": "10M"}},
                },
            ]

    monkeypatch.setattr(sym_module.socketio, "AsyncSimpleClient", DummyAsyncClient)

    # Minimal valid config for the plugin.
    config = {
        "currency": "USDT",
        "bo": 10,
        "signal_settings": (
            '{"api_url":"https://example.com","api_key":"x",'
            '"api_version":"v1","allowed_signals":[1]}'
        ),
    }

    def fake_check_entry_point(*_args, **_kwargs):
        return True

    async def fake_is_token_old_enough(*_args, **_kwargs):
        return True

    monkeypatch.setattr(
        plugin, "_SignalPlugin__check_entry_point", fake_check_entry_point
    )
    monkeypatch.setattr(plugin.data, "is_token_old_enough", fake_is_token_old_enough)

    orders = []

    async def fake_receive_buy_order(order, _config):
        orders.append(order)

    plugin.orders = types.SimpleNamespace(receive_buy_order=fake_receive_buy_order)

    await plugin.run(config)

    assert len(orders) == 1
    assert orders[0]["symbol"] == "BTC/USDT"
