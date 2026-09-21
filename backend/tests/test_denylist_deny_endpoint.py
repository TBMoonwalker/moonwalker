"""Tests for the per-trade denylist deny endpoint."""

import os

import pytest
import service.config as config_module
from controller.config import DenySymbolRequest, deny_symbol
from service.config import Config
from tortoise import Tortoise


class DummyRedis:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel, message) -> int:
        self.messages.append((channel, message))
        return 1


async def _make_instance(tmp_path, monkeypatch) -> Config:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    dummy = DummyRedis()
    monkeypatch.setattr(config_module, "redis_client", dummy)

    config = Config()
    await config.load_all()
    monkeypatch.setattr(Config, "_instance", config, raising=False)
    return config


@pytest.mark.asyncio
async def test_deny_symbol_endpoint_appends_token(
    tmp_path,
    monkeypatch,
) -> None:
    await _make_instance(tmp_path, monkeypatch)

    result = await deny_symbol.fn(DenySymbolRequest(symbol="FO0/USDT"))

    assert isinstance(result, dict)
    assert result["status"] == "denied"
    assert result["denied"] == "FO0/USDT"
    assert "FO0" in result["pair_denylist"]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_deny_symbol_endpoint_rejects_missing_symbol(
    tmp_path,
    monkeypatch,
) -> None:
    await _make_instance(tmp_path, monkeypatch)

    result = await deny_symbol.fn(DenySymbolRequest(symbol="    "))

    assert hasattr(result, "status_code")
    assert int(result.status_code) == 400

    await Tortoise.close_connections()
