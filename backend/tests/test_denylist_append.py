import asyncio
import os

import pytest
import service.config as config_module
from service.config import Config, parse_denylist_tokens, to_base_token
from service.filter import Filter
from tortoise import Tortoise


class DummyRedis:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel, message) -> int:
        self.messages.append((channel, message))
        return 1


async def _make_config(tmp_path, monkeypatch) -> tuple[Config, DummyRedis]:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    dummy = DummyRedis()
    monkeypatch.setattr(config_module, "redis_client", dummy)
    config = Config()
    await config.load_all()
    return config, dummy


@pytest.mark.asyncio
async def test_to_base_token_normalizes_variants() -> None:
    assert to_base_token("FO0/USDT") == "FO0"
    assert to_base_token("fo0/usdt") == "FO0"
    assert to_base_token("FO0-USDT") == "FO0"
    assert to_base_token("FO0USDT") == "FO0USDT"
    assert to_base_token("  fo0 ") == "FO0"
    assert to_base_token("") == ""


@pytest.mark.asyncio
async def test_parse_denylist_tokens_dedupes_and_ignores_sentinels() -> None:
    assert parse_denylist_tokens(None) == []
    assert parse_denylist_tokens(False) == []
    assert parse_denylist_tokens("false") == []
    assert parse_denylist_tokens("FO0, fo0 , ETH\nfo0") == ["FO0", "ETH"]


@pytest.mark.asyncio
async def test_append_denylist_token_dedupes_across_formats(
    tmp_path,
    monkeypatch,
) -> None:
    config, _ = await _make_config(tmp_path, monkeypatch)

    tokens = await config.append_denylist_token("FO0/USDT")
    assert tokens == ["FO0"]
    tokens = await config.append_denylist_token("fo0")
    assert tokens == ["FO0"]
    tokens = await config.append_denylist_token("ETH")
    assert tokens == ["FO0", "ETH"]

    assert parse_denylist_tokens(config.get("pair_denylist")) == ["FO0", "ETH"]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_concurrent_appends_do_not_clobber_each_other(
    tmp_path,
    monkeypatch,
) -> None:
    config, _ = await _make_config(tmp_path, monkeypatch)

    async def append(symbol: str) -> list[str]:
        return await config.append_denylist_token(symbol)

    results = list(await asyncio.gather(*[append(f"SYM{i}") for i in range(8)]))

    persisted = parse_denylist_tokens(config.get("pair_denylist"))
    # No concurrent task clobbered another's write: every token survived.
    assert len(persisted) == 8
    assert set(persisted) == {f"SYM{i}" for i in range(8)}
    # Each caller saw its own token and never regressed a peer's token.
    for index, result in enumerate(results):
        assert f"SYM{index}" in result
        assert set(result).issubset(set(persisted))

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_deny_block_future_entry_via_filter(tmp_path, monkeypatch) -> None:
    config, _ = await _make_config(tmp_path, monkeypatch)

    await config.append_denylist_token("FO0/USDT")
    deny_list = parse_denylist_tokens(config.get("pair_denylist"))
    filter_ = Filter()

    # A future signal for the denied base token is gated...
    assert filter_.is_on_deny_list("FO0", deny_list) is True
    # ...while an untouched symbol is still allowed.
    assert filter_.is_on_deny_list("ETH", deny_list) is False

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_deny_does_not_close_open_trade(tmp_path, monkeypatch) -> None:
    import model

    config, _ = await _make_config(tmp_path, monkeypatch)

    await model.OpenTrades.create(
        symbol="FO0/USDT",
        deal_id="deal-1",
        so_count=2,
        profit=1.5,
        cost=10.0,
    )

    tokens = await config.append_denylist_token("FO0")
    assert tokens == ["FO0"]

    # The open trade row is untouched by the deny write.
    row = await model.OpenTrades.get(symbol="FO0/USDT")
    assert row.so_count == 2
    assert row.profit == 1.5
    assert (await model.OpenTrades.filter(symbol="FO0/USDT").count()) == 1
    # No closed-trade row was created as a side effect of the deny write.
    assert (await model.ClosedTrades.filter(symbol="FO0/USDT").count()) == 0

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_merge_denylist_tokens_clears_list(tmp_path, monkeypatch) -> None:
    config, _ = await _make_config(tmp_path, monkeypatch)

    await config.append_denylist_token("FO0")
    await config.append_denylist_token("ETH")
    assert parse_denylist_tokens(config.get("pair_denylist")) == ["FO0", "ETH"]

    ordered = await config.merge_denylist_tokens([])
    assert ordered == []
    assert parse_denylist_tokens(config.get("pair_denylist")) == []

    await Tortoise.close_connections()
