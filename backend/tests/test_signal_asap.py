import asyncio
import types
from typing import Any

import pytest
import signals.asap as asap_module
from service.signal_runtime import SignalAdmissionBatch, SignalAdmissionDecision
from signals.asap import SignalPlugin, SymbolSelectionResult


@pytest.mark.asyncio
async def test_asap_run_uses_shared_admission_batch(monkeypatch) -> None:
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)

    monkeypatch.setattr(asap_module, "get_active_open_symbols", _async_symbols([]))

    # Force one iteration by flipping status after first sleep.
    async def fake_sleep(seconds: int) -> None:
        if seconds == 5:
            plugin.status = False

    monkeypatch.setattr(asap_module.asyncio, "sleep", fake_sleep)

    # Bypass internal checks and provide two passing symbols.
    async def fake_check_max_bots() -> None:
        return False

    async def fake_get_new_symbol_list(*_args) -> SymbolSelectionResult:
        return SymbolSelectionResult(
            symbols=("ETH/USDT", "BTC/USDT"),
            reason_code="ready",
        )

    async def fake_check_entry_point(_symbol) -> None:
        return True

    captured: dict[str, list[str]] = {}

    async def fake_resolve_signal_admission_batch(
        _config,
        _statistic,
        _autopilot,
        candidate_symbols,
    ) -> SignalAdmissionBatch:
        captured["candidate_symbols"] = list(candidate_symbols)
        return SignalAdmissionBatch(
            decisions=[
                SignalAdmissionDecision(
                    symbol="ETH/USDT",
                    admitted=False,
                    reason_code="skipped_ranked_out",
                    memory_status="fresh",
                    trust_direction="neutral",
                    trust_score=50.0,
                    available_slots=1,
                    competing_candidates=2,
                ),
                SignalAdmissionDecision(
                    symbol="BTC/USDT",
                    admitted=True,
                    reason_code="admitted_trust_priority",
                    memory_status="fresh",
                    trust_direction="favored",
                    trust_score=75.0,
                    available_slots=1,
                    competing_candidates=2,
                ),
            ]
        )

    monkeypatch.setattr(plugin, "_SignalPlugin__check_max_bots", fake_check_max_bots)
    monkeypatch.setattr(
        plugin, "_SignalPlugin__get_new_symbol_list", fake_get_new_symbol_list
    )
    monkeypatch.setattr(
        plugin, "_SignalPlugin__check_entry_point", fake_check_entry_point
    )
    monkeypatch.setattr(
        asap_module,
        "resolve_signal_admission_batch",
        fake_resolve_signal_admission_batch,
    )

    async def fake_resolve_signal_entry_orders(
        _config,
        _statistic,
        _autopilot,
        admitted_symbols,
        *,
        signal_name,
        strategy_name,
        timeframe,
    ) -> dict[str, types.SimpleNamespace]:
        assert admitted_symbols == ["BTC/USDT"]
        assert signal_name == "asap"
        assert strategy_name is None
        assert timeframe == "1m"
        return {
            "BTC/USDT": types.SimpleNamespace(
                symbol="BTC/USDT",
                order_size=17.5,
                baseline_order_size=10.0,
                suggested_order_size=17.5,
                entry_size_applied=True,
                reason_code="quick_profitable_closes",
                memory_status="fresh",
                trust_direction="favored",
                trust_score=75.0,
                signal_name="asap",
                strategy_name=None,
                timeframe="1m",
                metadata_json='{"entry_sizing":{"applied":true}}',
            )
        }

    monkeypatch.setattr(
        asap_module,
        "resolve_signal_entry_orders",
        fake_resolve_signal_entry_orders,
    )
    monkeypatch.setattr(
        asap_module,
        "SpotSidestepCampaignService",
        types.SimpleNamespace(
            instance=_async_value(types.SimpleNamespace(record_long_signal=_async_noop))
        ),
    )

    orders = []

    async def fake_receive_buy_order(order, _config) -> None:
        orders.append(order)

    plugin.orders = types.SimpleNamespace(receive_buy_order=fake_receive_buy_order)

    await plugin.run({"bo": 10})

    assert captured["candidate_symbols"] == ["ETH/USDT", "BTC/USDT"]
    assert len(orders) == 1
    assert orders[0]["symbol"] == "BTC/USDT"
    assert orders[0]["ordersize"] == 17.5
    assert orders[0]["baseline_order_size"] == 10.0
    assert orders[0]["entry_size_applied"] is True
    assert orders[0]["metadata_json"] == '{"entry_sizing":{"applied":true}}'
    queued_symbols = await watcher_queue.get()
    assert queued_symbols == ["BTC/USDT"]


def _async_symbols(symbols: list[str]):
    async def _inner() -> list[str]:
        return list(symbols)

    return _inner


def _async_value(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner


async def _async_noop(*_args, **_kwargs) -> None:
    return None


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

    result = await plugin._SignalPlugin__get_new_symbol_list(
        tuple(),
        plugin.config.get("symbol_list"),
        plugin._strategy_timeframe,
        plugin._required_history_days,
        plugin._required_history_candles,
    )

    assert result.symbols == tuple()
    assert result.reason_code == "insufficient_history"
    assert watcher_queue.empty() is True


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


@pytest.mark.asyncio
async def test_asap_missing_symbol_list_logs_app_config_message(monkeypatch) -> None:
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)
    plugin.config = {}
    captured: list[str] = []

    def fake_error(message: str, *args: object) -> None:
        captured.append(message % args if args else message)

    monkeypatch.setattr(asap_module.logging, "error", fake_error)

    result = await plugin._SignalPlugin__get_new_symbol_list(
        tuple(),
        plugin.config.get("symbol_list"),
        "1m",
        30,
        200,
    )

    assert result.symbols == tuple()
    assert result.reason_code == "missing_config"
    assert len(captured) == 1
    assert "config.ini" not in captured[0]
    assert "app configuration" in captured[0]


@pytest.mark.asyncio
async def test_asap_run_does_not_log_stale_config_ini_message(monkeypatch) -> None:
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)
    captured: list[str] = []

    async def fake_sleep(seconds: int) -> None:
        if seconds == 5:
            plugin.status = False

    async def fake_check_max_bots() -> None:
        return False

    async def fake_get_new_symbol_list(*_args) -> SymbolSelectionResult:
        return SymbolSelectionResult(
            symbols=tuple(),
            reason_code="insufficient_history",
        )

    def fake_error(message: str, *args: object) -> None:
        captured.append(message % args if args else message)

    monkeypatch.setattr(asap_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(asap_module, "get_active_open_symbols", _async_symbols([]))
    monkeypatch.setattr(plugin, "_SignalPlugin__check_max_bots", fake_check_max_bots)
    monkeypatch.setattr(
        plugin,
        "_SignalPlugin__get_new_symbol_list",
        fake_get_new_symbol_list,
    )
    monkeypatch.setattr(asap_module.logging, "error", fake_error)

    await plugin.run({"bo": 10})

    assert captured == []
