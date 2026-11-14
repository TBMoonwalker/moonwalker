"""Tests for the per-trade denylist deny endpoint."""

import asyncio
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
    # The response carries the generation advanced by the append so other
    # dashboard clients can detect the invalidation immediately.
    assert result["config_revision"] == 1

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_deny_symbol_endpoint_advances_revision_on_each_append(
    tmp_path,
    monkeypatch,
) -> None:
    await _make_instance(tmp_path, monkeypatch)

    first = await deny_symbol.fn(DenySymbolRequest(symbol="FO0/USDT"))
    second = await deny_symbol.fn(DenySymbolRequest(symbol="ETH"))

    assert first["config_revision"] == 1
    assert second["config_revision"] == 2
    assert "FO0" in second["pair_denylist"]
    assert "ETH" in second["pair_denylist"]

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


@pytest.mark.asyncio
async def test_deny_response_keeps_its_list_and_revision_together(
    tmp_path, monkeypatch
):
    """A second writer cannot pair its newer revision with the first list."""
    config = await _make_instance(tmp_path, monkeypatch)
    first_committed = asyncio.Event()
    second_committed = asyncio.Event()
    original = config.append_denylist_token_with_revision

    async def interleaved(symbol):
        result = await original(symbol)
        if symbol == "FOO/USDT":
            first_committed.set()
            await second_committed.wait()
        return result

    monkeypatch.setattr(config, "append_denylist_token_with_revision", interleaved)

    async def second_writer():
        await first_committed.wait()
        await original("ETH/USDT")
        second_committed.set()

    try:
        first, _ = await asyncio.gather(
            deny_symbol.fn(DenySymbolRequest(symbol="FOO/USDT")), second_writer()
        )
        assert first["pair_denylist"] == ["FOO"]
        assert first["config_revision"] == 1
        current, revision = await config.snapshot_with_revision()
        assert current["pair_denylist"] == "FOO,ETH"
        assert revision == 2
    finally:
        await Tortoise.close_connections()
