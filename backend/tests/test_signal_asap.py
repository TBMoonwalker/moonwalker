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


@pytest.mark.asyncio
async def test_asap_skips_symbols_with_insufficient_history(monkeypatch) -> None:
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)
    plugin.config = {"symbol_list": "BTC/USDT"}
    plugin._strategy_timeframe = "1m"
    plugin._required_history_days = 30
    plugin._required_history_candles = 200

    async def fake_has_sufficient_resampled_history(*_args, **_kwargs) -> bool:
        return False

    async def fake_add_history_data_for_symbol(*_args, **_kwargs) -> bool:
        return True

    async def fake_get_resampled_history_candle_count(*_args, **_kwargs) -> int:
        return 120

    plugin.data = types.SimpleNamespace(
        has_sufficient_resampled_history=fake_has_sufficient_resampled_history,
        add_history_data_for_symbol=fake_add_history_data_for_symbol,
        get_resampled_history_candle_count=fake_get_resampled_history_candle_count,
    )

    symbols = await plugin._SignalPlugin__get_new_symbol_list(tuple())

    assert symbols == []
    queued_symbols = await watcher_queue.get()
    assert queued_symbols == []


@pytest.mark.asyncio
async def test_asap_fetches_symbol_list_with_async_http_client(monkeypatch) -> None:
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)
    captured: dict[str, Any] = {}

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, list[str]]:
            return {"pairs": ["BTC/USDT", "ETH/USDT"]}

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self) -> "DummyAsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str) -> DummyResponse:
            captured["url"] = url
            return DummyResponse()

    async def fail_to_thread(*_args, **_kwargs) -> None:
        raise AssertionError(
            "ASAP URL fetch should not offload sync HTTP via to_thread"
        )

    monkeypatch.setattr(asap_module.httpx, "AsyncClient", DummyAsyncClient)
    monkeypatch.setattr(asap_module.asyncio, "to_thread", fail_to_thread)

    result = await plugin._SignalPlugin__fetch_symbol_list_from_url(
        "https://example.invalid/pairs"
    )

    assert result == ["BTC/USDT", "ETH/USDT"]
    assert captured["url"] == "https://example.invalid/pairs"
    assert captured["timeout"] == 10.0
