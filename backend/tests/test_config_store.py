import os
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
import service.config as config_module
from service.config import Config
from service.config_persistence import should_persist_config_value
from tortoise import Tortoise


class DummyRedis:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel, message) -> int:
        self.messages.append((channel, message))
        return 1


@pytest.mark.asyncio
async def test_config_set_and_load(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    await config.set("timezone", {"value": "Europe/London", "type": "str"})
    await config.load_all()

    assert config.get("timezone") == "Europe/London"

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_batch_set_persists_false_bool(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    await config.batch_set({"dry_run": {"value": False, "type": "bool"}})
    await config.load_all()

    assert config.get("dry_run") is False

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_set_persists_canonical_signal_settings(
    tmp_path,
    monkeypatch,
) -> None:
    """Signal settings should have deterministic versioned JSON storage."""
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    await config.load_all()
    await config.set(
        "signal_settings",
        {
            "value": {
                "allowed_signals": ["LONG", "STRONG_LONG"],
                "api_key": "secret",
                "api_url": "https://signals.example",
            },
            "type": "str",
        },
    )

    import model

    row = await model.AppConfig.get(key="signal_settings")
    assert row.value == (
        '{"allowed_signals":["LONG","STRONG_LONG"],"api_key":"secret",'
        '"api_url":"https://signals.example","schema_version":1}'
    )
    assert config.get("signal_settings") == row.value

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_batch_set_clears_false_string_value(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    await config.set("signal_strategy", {"value": "ema_low", "type": "str"})
    await config.batch_set({"signal_strategy": {"value": False, "type": "str"}})
    await config.load_all()

    assert config.get("signal_strategy") is None

    import model

    assert await model.AppConfig.filter(key="signal_strategy").exists() is False

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_batch_set_clears_null_string_value(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    await config.set("timezone", {"value": "Europe/Vienna", "type": "str"})
    await config.batch_set({"timezone": {"value": None, "type": "str"}})
    await config.load_all()

    assert config.get("timezone") is None

    import model

    assert await model.AppConfig.filter(key="timezone").exists() is False

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_set_updates_cache_without_reload(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    await config.set("timezone", {"value": "Europe/Vienna", "type": "str"})

    assert config.get("timezone") == "Europe/Vienna"

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_batch_set_updates_cache_without_reload(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    await config.batch_set(
        {
            "exchange": {"value": "binance", "type": "str"},
            "dry_run": {"value": False, "type": "bool"},
        }
    )

    assert config.get("exchange") == "binance"
    assert config.get("dry_run") is False

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_batch_set_can_skip_subscriber_notifications(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    redis = DummyRedis()
    monkeypatch.setattr(config_module, "redis_client", redis)

    notified_snapshots: list[dict[str, object]] = []
    config = Config()
    config.subscribe(lambda snapshot: notified_snapshots.append(snapshot))

    await config.batch_set(
        {"ai_trust_runtime_status": {"value": "provider_unavailable", "type": "str"}},
        notify_subscribers=False,
    )

    assert config.get("ai_trust_runtime_status") == "provider_unavailable"
    assert notified_snapshots == []
    assert redis.messages == []

    import model

    row = await model.AppConfig.get(key="ai_trust_runtime_status")
    assert row.value == "provider_unavailable"

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_handle_change_message_ignores_same_instance(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    redis = DummyRedis()
    monkeypatch.setattr(config_module, "redis_client", redis)

    config = Config()
    await config.set("timezone", {"value": "Europe/Vienna", "type": "str"})

    await config._handle_change_message(
        '{"source": "%s", "keys": ["timezone"]}' % config._instance_id
    )

    assert config.get("timezone") == "Europe/Vienna"
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_snapshot_returns_defensive_copy(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    await config.load_all()

    snapshot = config.snapshot()
    snapshot["signal_plugins"].append("fake_plugin")

    assert "fake_plugin" not in config.snapshot()["signal_plugins"]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_snapshot_ignores_removed_legacy_autopilot_max_fund_key(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    import model

    await model.AppConfig.create(
        key="autopilot_max_fund", value="250", value_type="int"
    )

    config = Config()
    await config.load_all()

    snapshot = config.snapshot()
    assert snapshot["capital_max_fund"] == 0.0
    assert "autopilot_max_fund" not in snapshot
    assert config.get("autopilot_max_fund") is None

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_set_rejects_removed_legacy_autopilot_max_fund_key(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    with pytest.raises(
        ValueError,
        match=(
            "Config key 'autopilot_max_fund' was removed in v1.4.0.0. "
            "Use 'capital_max_fund' instead."
        ),
    ):
        await config.set("autopilot_max_fund", {"value": 250, "type": "int"})

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_subscribers_receive_defensive_snapshot(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    received_configs: list[dict[str, object]] = []

    def subscriber(snapshot: dict[str, object]) -> None:
        received_configs.append(snapshot)

    config.subscribe(subscriber)
    await config.set("timezone", {"value": "Europe/Vienna", "type": "str"})

    assert received_configs
    assert received_configs[-1]["timezone"] == "Europe/Vienna"

    received_configs[-1]["timezone"] = "mutated"

    assert config.get("timezone") == "Europe/Vienna"
    assert config.snapshot()["timezone"] == "Europe/Vienna"

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_reload_updates_only_changed_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    redis = DummyRedis()
    monkeypatch.setattr(config_module, "redis_client", redis)

    import model

    await model.AppConfig.create(
        key="timezone", value="Europe/Vienna", value_type="str"
    )
    await model.AppConfig.create(key="exchange", value="binance", value_type="str")

    config = Config()
    await config.load_all()

    await model.AppConfig.filter(key="timezone").update(value="Europe/London")
    await config._handle_change_message('{"source": "remote", "keys": ["timezone"]}')

    assert config.get("timezone") == "Europe/London"
    assert config.get("exchange") == "binance"

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_load_all_applies_tp_spike_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    await config.load_all()

    assert config.get("tp_spike_confirm_enabled") is False
    assert config.get("tp_spike_confirm_seconds") == 3.0
    assert config.get("tp_spike_confirm_ticks") == 0
    assert config.get("tp_limit_prearm_enabled") is False
    assert config.get("tp_limit_prearm_margin_percent") == 0.25
    assert config.get("capital_reserve_safety_orders") is False
    snapshot = config.snapshot()
    assert snapshot["tp_spike_confirm_enabled"] is False
    assert snapshot["tp_spike_confirm_seconds"] == 3.0
    assert snapshot["tp_spike_confirm_ticks"] == 0
    assert snapshot["tp_limit_prearm_enabled"] is False
    assert snapshot["tp_limit_prearm_margin_percent"] == 0.25
    assert snapshot["capital_reserve_safety_orders"] is False

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_load_all_clears_removed_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    import model

    await model.AppConfig.create(
        key="timezone", value="Europe/Vienna", value_type="str"
    )

    config = Config()
    await config.load_all()
    assert config.get("timezone") == "Europe/Vienna"

    await model.AppConfig.filter(key="timezone").delete()
    await config.load_all()

    assert config.get("timezone") is None

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_load_all_ignores_removed_trade_mode_rows(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    import model

    await model.AppConfig.create(
        key="trade_lifecycle_mode",
        value="classic_dca",
        value_type="str",
    )
    await model.AppConfig.create(
        key="dynamic_dca",
        value=True,
        value_type="bool",
    )

    config = Config()
    await config.load_all()

    assert config.get("trade_mode") == "dynamic_dca"
    assert config.snapshot()["trade_mode"] == "dynamic_dca"
    assert config.get("delisting_protection_enabled") is False
    assert config.get("delisting_schedule_use_trading_credentials") is False
    assert config.get("delisting_schedule_api_key") == ""
    assert config.get("delisting_schedule_api_secret") == ""
    assert "dynamic_dca" not in config.snapshot()
    assert "trade_lifecycle_mode" not in config.snapshot()
    assert "dynamic_dca" not in config.raw_snapshot()
    assert "trade_lifecycle_mode" not in config.raw_snapshot()

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_load_all_derives_sidestep_from_legacy_upgrade_rows(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    import model

    await model.AppConfig.create(
        key="trade_lifecycle_mode",
        value="sidestep_reentry",
        value_type="str",
    )
    await model.AppConfig.create(
        key="sidestep_campaign_enabled",
        value=True,
        value_type="bool",
    )
    await model.AppConfig.create(
        key="sidestep_bearish_strategy",
        value="ema20_swing_reverse",
        value_type="str",
    )
    await model.AppConfig.create(
        key="sidestep_reentry_strategy",
        value="ema20_swing",
        value_type="str",
    )

    config = Config()
    await config.load_all()

    assert config.get("trade_mode") == "dynamic_dca"
    assert config.snapshot()["trade_mode"] == "dynamic_dca"
    assert "trade_lifecycle_mode" not in config.snapshot()
    assert "sidestep_campaign_enabled" not in config.snapshot()
    assert "trade_lifecycle_mode" not in config.raw_snapshot()
    assert "sidestep_campaign_enabled" not in config.raw_snapshot()
    assert (await model.AppConfig.get(key="trade_mode")).value == "dynamic_dca"

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_config_set_rejects_removed_trade_mode_bridge_key(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    with pytest.raises(
        ValueError,
        match=(
            "Config key 'trade_lifecycle_mode' was removed in this release. "
            "Use 'trade_mode' instead."
        ),
    ):
        await config.set(
            "trade_lifecycle_mode",
            {"value": "classic_dca", "type": "str"},
        )

    await Tortoise.close_connections()


def test_config_discovers_runtime_metadata_relative_to_backend_root(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    config = Config()

    strategies = config._Config__get_strategies()
    signal_plugins = config._Config__get_filenames_in_directory("signals")

    assert "ema20_swing" in strategies
    assert "ema20_swing_reverse" in strategies
    assert "ema_swing" in strategies
    assert "ema_swing_reverse" not in strategies
    assert "asap" in signal_plugins


def test_config_directory_scan_wraps_oserror(monkeypatch) -> None:
    config = Config()

    def fail_walk(*_args, **_kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(config_module.os, "walk", fail_walk)

    with pytest.raises(IOError, match="disk failure"):
        config._Config__get_filenames_in_directory("signals")


def test_config_directory_scan_propagates_unexpected_errors(monkeypatch) -> None:
    config = Config()

    def fail_walk(*_args, **_kwargs):
        raise TypeError("unexpected walker bug")

    monkeypatch.setattr(config_module.os, "walk", fail_walk)

    with pytest.raises(TypeError, match="unexpected walker bug"):
        config._Config__get_filenames_in_directory("signals")


def test_should_persist_config_value_matches_existing_semantics() -> None:
    assert should_persist_config_value("str", "binance") is True
    assert should_persist_config_value("str", None) is False
    assert should_persist_config_value("str", False) is False
    assert should_persist_config_value("bool", False) is True
    assert should_persist_config_value("int", 0) is True
    assert should_persist_config_value("float", 0.0) is True


@pytest.mark.asyncio
async def test_config_snapshot_keeps_defaults_and_metadata_out_of_persisted_entries(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    await config.load_all()

    assert "tp_spike_confirm_enabled" not in config._store._entries
    assert "tp_limit_prearm_enabled" not in config._store._entries
    assert "capital_reserve_safety_orders" not in config._store._entries
    assert "signal_plugins" not in config._store._entries
    assert config.snapshot()["tp_spike_confirm_enabled"] is False
    assert config.snapshot()["tp_limit_prearm_enabled"] is False
    assert config.snapshot()["capital_reserve_safety_orders"] is False
    assert "asap" in config.snapshot()["signal_plugins"]

    await Tortoise.close_connections()


class _ListenerPubSub:
    """Controllable subscription for listener lifecycle regressions."""

    def __init__(
        self, messages: Sequence[str] = (), error: Exception | None = None
    ) -> None:
        import asyncio

        self.messages = messages
        self.error = error
        self.subscribed = asyncio.Event()
        self.closed = False
        self.block = asyncio.Event()

    async def __aenter__(self) -> "_ListenerPubSub":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        del exc_type, exc, tb
        self.closed = True

    async def subscribe(self, channel: str) -> None:
        assert channel == config_module.CONFIG_CHANNEL
        self.subscribed.set()
        if self.error:
            raise self.error

    async def listen(self) -> AsyncIterator[dict[str, str]]:
        yield {"type": "subscribe", "data": "1"}
        for message in self.messages:
            yield {"type": "message", "data": message}
        await self.block.wait()


@pytest.mark.asyncio
async def test_config_instance_does_not_spawn_unowned_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loading config must not create subscriptions outside its lifespan."""
    import asyncio
    from unittest.mock import AsyncMock

    monkeypatch.setattr(Config, "_instance", None)
    monkeypatch.setattr(Config, "_lock", asyncio.Lock())
    monkeypatch.setattr(Config, "load_all", AsyncMock())
    config = await Config.instance()
    try:
        assert config._listener_task is None
    finally:
        if config._listener_task is not None:
            config._listener_task.cancel()
            await asyncio.gather(config._listener_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_config_listener_reconnects_and_reloads_then_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reconnect and resync before handling new change notifications."""
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from redis.exceptions import ConnectionError

    first = _ListenerPubSub(error=ConnectionError("injected disconnect"))
    recovered = _ListenerPubSub(messages=['{"keys":["timezone"]}'])
    monkeypatch.setattr(
        config_module.redis_client, "pubsub", Mock(side_effect=[first, recovered])
    )
    monkeypatch.setattr(Config, "LISTENER_RETRY_INITIAL_SECONDS", 0.001, raising=False)
    config = Config()
    received = asyncio.Event()

    async def reload(keys: list[str] | None = None) -> None:
        if keys is not None:
            assert keys == ["timezone"]
            received.set()

    reload_mock = AsyncMock(side_effect=reload)
    monkeypatch.setattr(config, "reload", reload_mock)
    task = asyncio.create_task(config._listen())
    try:
        await asyncio.wait_for(received.wait(), timeout=0.5)
        assert first.closed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert recovered.closed
    assert config._listener_task is None
    assert reload_mock.await_args_list[0].args == ()


@pytest.mark.asyncio
async def test_config_listener_closes_on_cancellation_and_can_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each lifetime must release its subscription on cancellation."""
    import asyncio
    from unittest.mock import AsyncMock, Mock

    subscriptions = [_ListenerPubSub(), _ListenerPubSub()]
    monkeypatch.setattr(
        config_module.redis_client, "pubsub", Mock(side_effect=subscriptions)
    )
    config = Config()
    monkeypatch.setattr(config, "reload", AsyncMock())
    for subscription in subscriptions:
        task = asyncio.create_task(config._listen())
        await subscription.subscribed.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert subscription.closed
        assert config._listener_task is None


@pytest.mark.asyncio
async def test_config_listener_unexpected_failure_reaches_task_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected faults must reach the supervising lifespan."""
    import asyncio
    from unittest.mock import Mock

    subscription = _ListenerPubSub(error=ValueError("bad subscription"))
    monkeypatch.setattr(
        config_module.redis_client, "pubsub", Mock(return_value=subscription)
    )
    config = Config()
    with pytest.raises(ExceptionGroup) as caught:
        async with asyncio.TaskGroup() as group:
            group.create_task(config._listen())
    assert isinstance(caught.value.exceptions[0], ValueError)
    assert subscription.closed


@pytest.mark.asyncio
async def test_config_stop_listener_closes_subscription_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutdown joins subscription cleanup and tolerates repeated calls."""
    import asyncio
    from unittest.mock import AsyncMock, Mock

    subscription = _ListenerPubSub()
    monkeypatch.setattr(
        config_module.redis_client, "pubsub", Mock(return_value=subscription)
    )
    config = Config()
    monkeypatch.setattr(config, "reload", AsyncMock())
    task = asyncio.create_task(config._listen())
    await subscription.subscribed.wait()
    await config.stop_listener()
    assert task.done()
    assert subscription.closed
    assert config._listener_task is None
    await config.stop_listener()


@pytest.mark.asyncio
async def test_config_listener_retry_delay_is_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated transport failures must respect the backoff ceiling."""
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from redis.exceptions import ConnectionError

    failed = [
        _ListenerPubSub(error=ConnectionError("injected disconnect")) for _ in range(3)
    ]
    healthy = _ListenerPubSub()
    monkeypatch.setattr(
        config_module.redis_client, "pubsub", Mock(side_effect=[*failed, healthy])
    )
    monkeypatch.setattr(Config, "LISTENER_RETRY_INITIAL_SECONDS", 1.0)
    monkeypatch.setattr(Config, "LISTENER_RETRY_MAX_SECONDS", 2.0)
    delays = []
    original_sleep = asyncio.sleep

    async def record_delay(delay: float) -> None:
        delays.append(delay)
        await original_sleep(0)

    monkeypatch.setattr(config_module.asyncio, "sleep", record_delay)
    config = Config()
    monkeypatch.setattr(config, "reload", AsyncMock())
    task = asyncio.create_task(config._listen())
    try:
        await asyncio.wait_for(healthy.subscribed.wait(), timeout=0.5)
        assert delays == [1.0, 2.0, 2.0]
        assert all(subscription.closed for subscription in failed)
    finally:
        await config.stop_listener()
        assert task.done()


@pytest.mark.asyncio
async def test_config_listener_resyncs_after_client_resubscribe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client-internal reconnection must refresh changes whose messages were lost."""
    import asyncio
    from unittest.mock import AsyncMock, Mock

    reconnect = asyncio.Event()
    initial_reload = asyncio.Event()
    resynced = asyncio.Event()
    persisted = {"timezone": "UTC"}
    snapshots: list[str] = []

    class ResubscribingPubSub(_ListenerPubSub):
        async def listen(self) -> AsyncIterator[dict[str, str]]:
            yield {"type": "subscribe", "data": "1"}
            await reconnect.wait()
            yield {"type": "subscribe", "data": "1"}
            await self.block.wait()

    async def reload(keys: list[str] | None = None) -> None:
        assert keys is None
        snapshots.append(persisted["timezone"])
        (initial_reload if len(snapshots) == 1 else resynced).set()

    subscription = ResubscribingPubSub()
    monkeypatch.setattr(
        config_module.redis_client, "pubsub", Mock(return_value=subscription)
    )
    config = Config()
    monkeypatch.setattr(config, "reload", AsyncMock(side_effect=reload))
    task = asyncio.create_task(config._listen())
    try:
        await asyncio.wait_for(initial_reload.wait(), timeout=0.5)
        persisted["timezone"] = "Europe/Vienna"
        reconnect.set()
        await asyncio.wait_for(resynced.wait(), timeout=0.5)
        assert snapshots == ["UTC", "Europe/Vienna"]
    finally:
        await config.stop_listener()
        assert task.done()
