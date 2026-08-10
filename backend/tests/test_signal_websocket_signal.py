import asyncio
import json
import types
from datetime import UTC, datetime, timedelta
from typing import Any

import model
import pytest
import signals.websocket_signal as websocket_signal_module
from service.signal_runtime import SignalAdmissionBatch, SignalAdmissionDecision
from signals.websocket_signal import SignalPlugin


class DummyOpenTrades:
    rows = []

    @classmethod
    def all(cls):
        return cls()

    async def values(self, *args, **kwargs) -> list:
        return list(self.rows)


def _async_result(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner


async def _async_noop(*_args, **_kwargs) -> None:
    return None


def _admission_batch(symbol: str = "DYM/USDC") -> SignalAdmissionBatch:
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


def _entry_order_decisions(
    symbol: str = "DYM/USDC",
    *,
    signal_name: str = "websocket_signal:sig-1",
    strategy_name: str | None = "momentum-confirmation",
    strategy_slug: str | None = None,
    strategy_version: int | None = None,
    timeframe: str = "1h",
) -> dict[str, types.SimpleNamespace]:
    return {
        symbol: types.SimpleNamespace(
            symbol=symbol,
            order_size=25.0,
            baseline_order_size=25.0,
            suggested_order_size=25.0,
            entry_size_applied=False,
            reason_code=None,
            memory_status="fresh",
            trust_direction="neutral",
            trust_score=50.0,
            signal_name=signal_name,
            strategy_name=strategy_name,
            strategy_slug=strategy_slug or strategy_name,
            strategy_version=strategy_version,
            timeframe=timeframe,
            metadata_json='{"entry_sizing":{"applied":false}}',
        )
    }


def _payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "exchange": "binance",
        "symbol": "DYMUSDC",
        "timeframe": "1h",
        "strategy_family": "momentum-confirmation",
        "decision": "take_trade",
        "confidence": 78,
        "observed_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "market_state": "healthy",
        "rationale_codes": ["trend_aligned"],
        "feature_snapshot": {
            "trend_score": 0.012218649517684949,
            "volatility_percentile": 0.0,
            "spread_bps": 12.69841269841218,
            "volume_regime": "healthy",
            "freshness_ms": 2206173,
        },
        "publish_reason": "health_transition",
        "signal_id": "sig-1",
        "sequence": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "timezone": "UTC",
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _patch_common_services(monkeypatch):
    DummyOpenTrades.rows = []
    monkeypatch.setattr(model, "OpenTrades", DummyOpenTrades)
    monkeypatch.setattr(
        websocket_signal_module,
        "SpotSidestepCampaignService",
        types.SimpleNamespace(
            instance=_async_result(
                types.SimpleNamespace(record_long_signal=_async_noop)
            )
        ),
    )
    monkeypatch.setattr(
        websocket_signal_module,
        "resolve_signal_admission_batch",
        _async_result(_admission_batch()),
    )
    monkeypatch.setattr(
        websocket_signal_module,
        "is_max_bots_reached",
        _async_result(False),
    )


def _config(**overrides: Any) -> dict[str, Any]:
    config = {
        "exchange": "binance",
        "currency": "USDC",
        "bo": 25,
        "max_bots": 3,
        "signal_settings": json.dumps(
            {
                "websocket_url": "ws://signals.example.test/stream",
                "headers": {"Authorization": "Bearer token"},
                "accepted_market_states": ["healthy"],
                "min_confidence": 50,
                "reconnect_delay_seconds": 1,
            }
        ),
    }
    config.update(overrides)
    return config


async def _run_plugin_once(
    monkeypatch,
    plugin: SignalPlugin,
    payload: dict[str, Any],
    *,
    sent_messages: list[str] | None = None,
) -> None:
    class DummyWebsocket:
        def __init__(self) -> None:
            self._received = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def recv(self) -> str:
            if self._received:
                plugin.status = False
                raise websocket_signal_module.ConnectionClosed(None, None)
            self._received = True
            plugin.status = False
            return json.dumps(payload)

        async def send(self, message: str) -> None:
            if sent_messages is not None:
                sent_messages.append(message)

    def fake_connect(*_args, **_kwargs):
        return DummyWebsocket()

    monkeypatch.setattr(websocket_signal_module, "connect", fake_connect)

    async def fake_sleep(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(websocket_signal_module.asyncio, "sleep", fake_sleep)
    await plugin.run(_config())


@pytest.mark.asyncio
async def test_websocket_signal_opens_trade_from_take_trade_payload(monkeypatch):
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)

    monkeypatch.setattr(
        plugin.data,
        "is_token_old_enough",
        _async_result(True),
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
        assert admitted_symbols == ["DYM/USDC"]
        assert signal_name == "websocket_signal:sig-1"
        assert strategy_name == "momentum-confirmation"
        assert timeframe == "1h"
        return _entry_order_decisions(
            signal_name=signal_name,
            strategy_name=strategy_name,
            timeframe=timeframe,
        )

    monkeypatch.setattr(
        websocket_signal_module,
        "resolve_signal_entry_orders",
        fake_resolve_signal_entry_orders,
    )

    orders = []

    async def fake_receive_buy_order(order, _config) -> None:
        orders.append(order)

    plugin.orders = types.SimpleNamespace(receive_buy_order=fake_receive_buy_order)

    await _run_plugin_once(monkeypatch, plugin, _payload())

    assert len(orders) == 1
    assert orders[0]["symbol"] == "DYM/USDC"
    assert orders[0]["ordersize"] == 25.0
    assert orders[0]["signal_name"] == "websocket_signal:sig-1"
    assert orders[0]["strategy_name"] == "momentum-confirmation"
    metadata = json.loads(orders[0]["metadata_json"])
    assert metadata["entry_sizing"]["applied"] is False
    assert metadata["websocket_signal"]["signal_id"] == "sig-1"
    assert metadata["websocket_signal"]["rationale_codes"] == ["trend_aligned"]
    assert await watcher_queue.get() == ["DYM/USDC"]


@pytest.mark.asyncio
async def test_websocket_signal_ignores_non_trade_decision(monkeypatch):
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)
    orders = []

    async def fake_receive_buy_order(order, _config) -> None:
        orders.append(order)

    plugin.orders = types.SimpleNamespace(receive_buy_order=fake_receive_buy_order)

    await _run_plugin_once(monkeypatch, plugin, _payload(decision="skip_trade"))

    assert orders == []
    assert watcher_queue.empty()


@pytest.mark.asyncio
async def test_websocket_signal_ignores_expired_signal(monkeypatch):
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)
    orders = []

    async def fake_receive_buy_order(order, _config) -> None:
        orders.append(order)

    plugin.orders = types.SimpleNamespace(receive_buy_order=fake_receive_buy_order)

    await _run_plugin_once(
        monkeypatch,
        plugin,
        _payload(expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat()),
    )

    assert orders == []
    assert watcher_queue.empty()


@pytest.mark.asyncio
async def test_websocket_signal_acknowledges_keepalive_message(monkeypatch):
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)
    orders = []
    sent_messages: list[str] = []

    async def fake_receive_buy_order(order, _config) -> None:
        orders.append(order)

    plugin.orders = types.SimpleNamespace(receive_buy_order=fake_receive_buy_order)

    await _run_plugin_once(
        monkeypatch,
        plugin,
        {
            "type": "keepalive",
            "sent_at": "2026-07-10T04:43:34.789201+00:00",
            "timezone": "UTC",
            "connection_id": "ws-ca5df5f62515",
            "last_sent_sequence": 0,
        },
        sent_messages=sent_messages,
    )

    assert orders == []
    assert watcher_queue.empty()
    assert [json.loads(message) for message in sent_messages] == [
        {"type": "keepalive_ack", "id": "ws-ca5df5f62515"}
    ]


@pytest.mark.asyncio
async def test_websocket_signal_sends_optional_subscription(monkeypatch):
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)
    sent_messages: list[str] = []
    config = _config(
        signal_settings=json.dumps(
            {
                "websocket_url": "ws://signals.example.test/stream",
                "subscribe_message": {"type": "subscribe", "symbols": ["DYMUSDC"]},
                "reconnect_delay_seconds": 1,
            }
        )
    )

    class DummyWebsocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def recv(self) -> str:
            plugin.status = False
            return json.dumps(_payload())

        async def send(self, message: str) -> None:
            sent_messages.append(message)

    monkeypatch.setattr(
        websocket_signal_module,
        "connect",
        lambda *_args, **_kwargs: DummyWebsocket(),
    )
    monkeypatch.setattr(plugin.data, "is_token_old_enough", _async_result(False))
    monkeypatch.setattr(websocket_signal_module.asyncio, "sleep", _async_noop)

    await plugin.run(config)

    assert sent_messages == ['{"symbols": ["DYMUSDC"], "type": "subscribe"}']


@pytest.mark.asyncio
async def test_websocket_signal_connects_without_headers_for_url_token(monkeypatch):
    watcher_queue = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)
    captured_kwargs: dict[str, Any] = {}
    config = _config(
        signal_settings=json.dumps(
            {
                "websocket_url": (
                    "ws://localhost:8000/v1/signals/stream?token=dev-token"
                ),
                "reconnect_delay_seconds": 1,
            }
        )
    )

    class DummyWebsocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def recv(self) -> str:
            plugin.status = False
            return json.dumps(_payload())

        async def send(self, _message: str) -> None:
            raise AssertionError("subscription should not be sent")

    def fake_connect(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return DummyWebsocket()

    monkeypatch.setattr(websocket_signal_module, "connect", fake_connect)
    monkeypatch.setattr(plugin.data, "is_token_old_enough", _async_result(False))
    monkeypatch.setattr(websocket_signal_module.asyncio, "sleep", _async_noop)

    await plugin.run(config)

    assert captured_kwargs["additional_headers"] is None
