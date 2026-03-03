import asyncio
import types
from typing import Any

import model
import pytest
import signals.asap as asap_module
from signals.asap import SignalPlugin


class DummyTrades:
    @classmethod
    def all(cls):
        return cls()

    async def values_list(self, *args, **kwargs) -> list:
        return []

    def distinct(self) -> Any:
        return self


@pytest.mark.asyncio
async def test_asap_run_triggers_buy_order(monkeypatch) -> None:
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)

    # Patch model.Trades chain to return no running trades.
    monkeypatch.setattr(model, "Trades", DummyTrades)

    # Force one iteration by flipping status after first sleep.
    async def fake_sleep(_) -> None:
        plugin.status = False

    monkeypatch.setattr(asap_module.asyncio, "sleep", fake_sleep)

    # Bypass internal checks and provide a single symbol.
    async def fake_check_max_bots() -> None:
        return False

    async def fake_get_new_symbol_list(_) -> None:
        return ["BTC/USDT"]

    async def fake_check_entry_point(_symbol) -> None:
        return True

    monkeypatch.setattr(plugin, "_SignalPlugin__check_max_bots", fake_check_max_bots)
    monkeypatch.setattr(
        plugin, "_SignalPlugin__get_new_symbol_list", fake_get_new_symbol_list
    )
    monkeypatch.setattr(
        plugin, "_SignalPlugin__check_entry_point", fake_check_entry_point
    )

    orders = []

    async def fake_receive_buy_order(order, _config) -> None:
        orders.append(order)

    plugin.orders = types.SimpleNamespace(receive_buy_order=fake_receive_buy_order)

    await plugin.run({"bo": 10})

    assert len(orders) == 1
    assert orders[0]["symbol"] == "BTC/USDT"
    assert orders[0]["ordersize"] == 10
