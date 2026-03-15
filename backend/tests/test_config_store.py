import os

import pytest
import service.config as config_module
from service.config import Config
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
    await config.batch_set({"dry_run": '{"value": false, "type": "bool"}'})
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
    await config.batch_set({"signal_strategy": '{"value": false, "type": "str"}'})
    await config.load_all()

    assert config.get("signal_strategy") is None

    import model

    assert await model.AppConfig.filter(key="signal_strategy").exists() is False

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
            "exchange": '{"value": "binance", "type": "str"}',
            "dry_run": '{"value": false, "type": "bool"}',
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
    config._cache["timezone"] = "Europe/Vienna"

    await config._handle_change_message(
        '{"source": "%s", "keys": ["timezone"]}' % config._instance_id
    )

    assert config.get("timezone") == "Europe/Vienna"
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
    assert config._cache["tp_spike_confirm_enabled"] is False
    assert config._cache["tp_spike_confirm_seconds"] == 3.0
    assert config._cache["tp_spike_confirm_ticks"] == 0

    await Tortoise.close_connections()
