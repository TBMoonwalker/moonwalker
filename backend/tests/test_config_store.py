import os

import pytest
import service.config as config_module
from service.config import Config
from tortoise import Tortoise


class DummyRedis:
    async def publish(self, channel, message) -> int:
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
