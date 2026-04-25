import os

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
async def test_config_snapshot_mirrors_legacy_autopilot_max_fund_alias(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    config = Config()
    await config.set("autopilot_max_fund", {"value": 250, "type": "int"})
    await config.load_all()

    snapshot = config.snapshot()
    assert snapshot["capital_max_fund"] == 250
    assert snapshot["autopilot_max_fund"] == 250

    await config.set("capital_max_fund", {"value": 300, "type": "int"})
    snapshot = config.snapshot()
    assert snapshot["capital_max_fund"] == 300
    assert snapshot["autopilot_max_fund"] == 300

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
    snapshot = config.snapshot()
    assert snapshot["tp_spike_confirm_enabled"] is False
    assert snapshot["tp_spike_confirm_seconds"] == 3.0
    assert snapshot["tp_spike_confirm_ticks"] == 0

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


def test_config_discovers_runtime_metadata_relative_to_backend_root(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    config = Config()

    strategies = config._Config__get_filenames_in_directory("strategies")
    signal_plugins = config._Config__get_filenames_in_directory("signals")

    assert "ema_swing" in strategies
    assert "asap" in signal_plugins


def test_config_directory_scan_wraps_oserror(monkeypatch) -> None:
    config = Config()

    def fail_walk(*_args, **_kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(config_module.os, "walk", fail_walk)

    with pytest.raises(IOError, match="disk failure"):
        config._Config__get_filenames_in_directory("strategies")


def test_config_directory_scan_propagates_unexpected_errors(monkeypatch) -> None:
    config = Config()

    def fail_walk(*_args, **_kwargs):
        raise TypeError("unexpected walker bug")

    monkeypatch.setattr(config_module.os, "walk", fail_walk)

    with pytest.raises(TypeError, match="unexpected walker bug"):
        config._Config__get_filenames_in_directory("strategies")


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
    assert "signal_plugins" not in config._store._entries
    assert config.snapshot()["tp_spike_confirm_enabled"] is False
    assert "asap" in config.snapshot()["signal_plugins"]

    await Tortoise.close_connections()
