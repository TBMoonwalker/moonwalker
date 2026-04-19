import asyncio
import types
from typing import Any

import model
import pytest
import signals.sym_signals as sym_module
from service.signal_runtime import SignalAdmissionBatch, SignalAdmissionDecision
from signals.sym_signals import SignalPlugin


class DummyTrades:
    @classmethod
    def all(cls):
        return cls()

    async def values_list(self, *args, **kwargs) -> list:
        return []

    def distinct(self) -> Any:
        return self


class DummyOpenTrades:
    @classmethod
    def all(cls):
        return cls()

    async def values(self, *args, **kwargs) -> list:
        return []


def _admission_batch(symbol: str = "BTC/USDT") -> SignalAdmissionBatch:
    return SignalAdmissionBatch(
        decisions=[
            SignalAdmissionDecision(
                symbol=symbol,
                admitted=True,
                reason_code="admitted_capacity_available",
                memory_status="fresh",
                trust_direction="neutral",
                trust_score=50.0,
                available_slots=1,
                competing_candidates=1,
            )
        ]
    )


def _async_result(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner


def _entry_order_decisions(
    symbol: str = "BTC/USDT",
    *,
    order_size: float = 10.0,
    baseline_order_size: float = 10.0,
) -> dict[str, types.SimpleNamespace]:
    entry_size_applied = order_size != baseline_order_size
    return {
        symbol: types.SimpleNamespace(
            symbol=symbol,
            order_size=order_size,
            baseline_order_size=baseline_order_size,
            suggested_order_size=order_size,
            entry_size_applied=entry_size_applied,
            reason_code="quick_profitable_closes",
            memory_status="fresh",
            trust_direction="favored" if entry_size_applied else "neutral",
            trust_score=72.0 if entry_size_applied else 50.0,
            signal_name="sym_signals:1",
            strategy_name=None,
            timeframe="1m",
            metadata_json=(
                '{"entry_sizing":{"applied":true}}'
                if entry_size_applied
                else '{"entry_sizing":{"applied":false}}'
            ),
        )
    }


@pytest.mark.asyncio
async def test_sym_signals_run_uses_shared_admission_batch(monkeypatch) -> None:
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)

    monkeypatch.setattr(model, "OpenTrades", DummyOpenTrades)

    class DummyAsyncClient:
        def __init__(self):
            self.connected = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def connect(self, *_args, **_kwargs) -> None:
            self.connected = True

        async def disconnect(self) -> None:
            self.connected = False

        async def receive(self, *_, **__) -> list:
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

    async def fake_check_entry_point(*_args, **_kwargs) -> None:
        return True

    async def fake_is_token_old_enough(*_args, **_kwargs) -> None:
        return True

    monkeypatch.setattr(
        plugin, "_SignalPlugin__check_entry_point", fake_check_entry_point
    )
    monkeypatch.setattr(plugin.data, "is_token_old_enough", fake_is_token_old_enough)

    captured: dict[str, list[str]] = {}

    async def fake_resolve_signal_admission_batch(
        _config,
        _statistic,
        _autopilot,
        candidate_symbols,
    ) -> SignalAdmissionBatch:
        captured["candidate_symbols"] = list(candidate_symbols)
        return _admission_batch()

    monkeypatch.setattr(
        sym_module,
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
        assert signal_name == "sym_signals:1"
        assert strategy_name is None
        assert timeframe == "1m"
        return _entry_order_decisions(
            order_size=17.5,
            baseline_order_size=10.0,
        )

    monkeypatch.setattr(
        sym_module,
        "resolve_signal_entry_orders",
        fake_resolve_signal_entry_orders,
    )

    async def fake_get_profit() -> None:
        return {
            "upnl": 0,
            "profit_overall": 0,
            "funds_locked": 0,
            "autopilot": "none",
            "profit_week": {},
        }

    monkeypatch.setattr(plugin.statistic, "get_profit", fake_get_profit)

    orders = []

    async def fake_receive_buy_order(order, _config) -> None:
        orders.append(order)

    plugin.orders = types.SimpleNamespace(receive_buy_order=fake_receive_buy_order)

    await plugin.run(config)

    assert captured["candidate_symbols"] == ["BTC/USDT"]
    assert len(orders) == 1
    assert orders[0]["symbol"] == "BTC/USDT"
    assert orders[0]["ordersize"] == 17.5
    assert orders[0]["baseline_order_size"] == 10.0
    assert orders[0]["entry_size_applied"] is True
    queued_symbols = await watcher_queue.get()
    assert queued_symbols == ["BTC/USDT"]


@pytest.mark.asyncio
async def test_sym_signals_idle_timeout_does_not_force_immediate_reconnect(
    monkeypatch,
) -> None:
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)

    monkeypatch.setattr(model, "OpenTrades", DummyOpenTrades)

    class DummyAsyncClient:
        connect_calls = 0
        disconnect_calls = 0

        def __init__(self):
            self.connected = False
            self.receive_calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def connect(self, *_args, **_kwargs) -> None:
            self.connected = True
            DummyAsyncClient.connect_calls += 1

        async def disconnect(self) -> None:
            self.connected = False
            DummyAsyncClient.disconnect_calls += 1

        async def receive(self, *_, **__) -> list:
            self.receive_calls += 1
            if self.receive_calls == 1:
                raise sym_module.TimeoutError()

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

    config = {
        "currency": "USDT",
        "bo": 10,
        "signal_settings": (
            '{"api_url":"https://example.com","api_key":"x",'
            '"api_version":"v1","allowed_signals":[1]}'
        ),
    }

    async def fake_check_entry_point(*_args, **_kwargs) -> None:
        return True

    async def fake_is_token_old_enough(*_args, **_kwargs) -> None:
        return True

    monkeypatch.setattr(
        plugin, "_SignalPlugin__check_entry_point", fake_check_entry_point
    )
    monkeypatch.setattr(plugin.data, "is_token_old_enough", fake_is_token_old_enough)

    async def fake_get_profit() -> None:
        return {
            "upnl": 0,
            "profit_overall": 0,
            "funds_locked": 0,
            "autopilot": "none",
            "profit_week": {},
        }

    monkeypatch.setattr(plugin.statistic, "get_profit", fake_get_profit)
    monkeypatch.setattr(
        sym_module,
        "resolve_signal_admission_batch",
        _async_result(_admission_batch()),
    )
    monkeypatch.setattr(
        sym_module,
        "resolve_signal_entry_orders",
        _async_result(_entry_order_decisions()),
    )

    orders = []

    async def fake_receive_buy_order(order, _config) -> None:
        orders.append(order)

    plugin.orders = types.SimpleNamespace(receive_buy_order=fake_receive_buy_order)

    await plugin.run(config)

    assert len(orders) == 1
    assert DummyAsyncClient.connect_calls == 1
    assert DummyAsyncClient.disconnect_calls == 0


@pytest.mark.asyncio
async def test_sym_signals_idle_warning_mentions_no_events(monkeypatch) -> None:
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)
    plugin.SOCKET_IDLE_TIMEOUT_SECONDS = 1
    plugin.MAX_IDLE_TIMEOUTS_BEFORE_RECONNECT = 2

    monkeypatch.setattr(model, "OpenTrades", DummyOpenTrades)

    class DummyAsyncClient:
        def __init__(self):
            self.connected = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def connect(self, *_args, **_kwargs) -> None:
            self.connected = True

        async def disconnect(self) -> None:
            self.connected = False
            plugin.status = False

        async def receive(self, *_, **__) -> list:
            raise sym_module.TimeoutError()

    warnings = []

    def capture_warning(message, *args) -> None:
        warnings.append(message % args if args else message)

    monkeypatch.setattr(sym_module.socketio, "AsyncSimpleClient", DummyAsyncClient)
    monkeypatch.setattr(sym_module.logging, "warning", capture_warning)

    config = {
        "currency": "USDT",
        "bo": 10,
        "signal_settings": (
            '{"api_url":"https://example.com","api_key":"x",'
            '"api_version":"v1","allowed_signals":[1]}'
        ),
    }

    await plugin.run(config)

    assert any(
        "No websocket events were received since this connection was established."
        in entry
        for entry in warnings
    )


@pytest.mark.asyncio
async def test_sym_signals_error_event_logs_payload_and_uses_backoff(
    monkeypatch,
) -> None:
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)
    plugin.RECONNECT_DELAY_SECONDS = 3
    plugin.MAX_ERROR_RECONNECT_DELAY_SECONDS = 30

    monkeypatch.setattr(model, "OpenTrades", DummyOpenTrades)

    class DummyAsyncClient:
        def __init__(self):
            self.connected = False
            self.receive_calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def connect(self, *_args, **_kwargs) -> None:
            self.connected = True

        async def disconnect(self) -> None:
            self.connected = False

        async def receive(self, *_, **__) -> list:
            self.receive_calls += 1
            if self.receive_calls == 1:
                return ["error", {"message": "unauthorized", "code": "AUTH_401"}]

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

    warning_logs = []
    sleep_calls = []

    def capture_warning(message, *args) -> None:
        warning_logs.append(message % args if args else message)

    async def fake_sleep(seconds) -> None:
        sleep_calls.append(seconds)
        return None

    monkeypatch.setattr(sym_module.socketio, "AsyncSimpleClient", DummyAsyncClient)
    monkeypatch.setattr(sym_module.logging, "warning", capture_warning)
    monkeypatch.setattr(sym_module.asyncio, "sleep", fake_sleep)

    config = {
        "currency": "USDT",
        "bo": 10,
        "signal_settings": (
            '{"api_url":"https://example.com","api_key":"x",'
            '"api_version":"v1","allowed_signals":[1]}'
        ),
    }

    async def fake_check_entry_point(*_args, **_kwargs) -> None:
        return True

    async def fake_is_token_old_enough(*_args, **_kwargs) -> None:
        return True

    monkeypatch.setattr(
        plugin, "_SignalPlugin__check_entry_point", fake_check_entry_point
    )
    monkeypatch.setattr(plugin.data, "is_token_old_enough", fake_is_token_old_enough)

    async def fake_get_profit() -> None:
        return {
            "upnl": 0,
            "profit_overall": 0,
            "funds_locked": 0,
            "autopilot": "none",
            "profit_week": {},
        }

    monkeypatch.setattr(plugin.statistic, "get_profit", fake_get_profit)
    monkeypatch.setattr(
        sym_module,
        "resolve_signal_admission_batch",
        _async_result(_admission_batch()),
    )
    monkeypatch.setattr(
        sym_module,
        "resolve_signal_entry_orders",
        _async_result(_entry_order_decisions()),
    )

    orders = []

    async def fake_receive_buy_order(order, _config) -> None:
        orders.append(order)

    plugin.orders = types.SimpleNamespace(receive_buy_order=fake_receive_buy_order)

    await plugin.run(config)

    assert len(orders) == 1
    assert sleep_calls == [3]
    assert any("AUTH_401" in entry for entry in warning_logs)


@pytest.mark.asyncio
async def test_sym_signals_skips_buy_when_history_remains_insufficient(
    monkeypatch,
) -> None:
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)
    plugin.config = {
        "currency": "USDT",
        "bo": 10,
        "dynamic_dca": True,
    }
    plugin._currency = "USDT"
    plugin._strategy_timeframe = "1m"
    plugin._required_history_days = 30
    plugin._required_history_candles = 200

    monkeypatch.setattr(model, "OpenTrades", DummyOpenTrades)

    async def fake_check_entry_point(*_args, **_kwargs) -> bool:
        return True

    async def fake_is_token_old_enough(*_args, **_kwargs) -> bool:
        return True

    async def fake_add_history_data_for_symbol(*_args, **_kwargs) -> bool:
        return True

    async def fake_get_resampled_history_candle_count(*_args, **_kwargs) -> int:
        return 120

    monkeypatch.setattr(
        plugin, "_SignalPlugin__check_entry_point", fake_check_entry_point
    )
    plugin.data = types.SimpleNamespace(
        is_token_old_enough=fake_is_token_old_enough,
        add_history_data_for_symbol=fake_add_history_data_for_symbol,
        get_resampled_history_candle_count=fake_get_resampled_history_candle_count,
    )
    monkeypatch.setattr(
        sym_module,
        "resolve_signal_admission_batch",
        _async_result(_admission_batch()),
    )
    monkeypatch.setattr(
        sym_module,
        "resolve_signal_entry_orders",
        _async_result(_entry_order_decisions()),
    )

    orders = []

    async def fake_receive_buy_order(order, _config) -> None:
        orders.append(order)

    plugin.orders = types.SimpleNamespace(receive_buy_order=fake_receive_buy_order)

    await plugin._SignalPlugin__process_valid_signal(
        {
            "symbol": "BTC",
            "signal": "BOT_START",
            "signal_name_id": 1,
            "market_cap_rank": 1,
            "volume_24h": {"BINANCE": {"USDT": "10M"}},
        },
        "USDT",
        30,
    )

    assert orders == []
    assert watcher_queue.empty()
