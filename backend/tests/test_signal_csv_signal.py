import asyncio
import os
import types

import pytest
import signals.csv_signal as csv_signal_module
from signals.csv_signal import SignalPlugin
from tortoise import Tortoise


class _DummyOpenTradesZero:
    @classmethod
    def all(cls):
        return cls()

    async def count(self) -> int:
        return 0


class _DummyOpenTradesOne:
    @classmethod
    def all(cls):
        return cls()

    async def count(self) -> int:
        return 1


@pytest.mark.asyncio
async def test_csv_signal_imports_and_pushes_symbols(monkeypatch) -> None:
    watcher_queue: asyncio.Queue[list[str]] = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)

    monkeypatch.setattr(csv_signal_module.model, "OpenTrades", _DummyOpenTradesZero)

    async def fake_load_csv_content(_source: str) -> str:
        return (
            "date;symbol;price;amount\n"
            "18/08/2025 19:32:00;BTC/USDC;117644.41;0.00099153\n"
            "24/08/2025 15:04:00;BTC/USDC;112170.19;0.03863000\n"
        )

    monkeypatch.setattr(plugin, "_load_csv_content", fake_load_csv_content)

    imported = []
    history_calls = []

    async def fake_import_from_csv(**kwargs):
        imported.append(kwargs)
        plugin.status = False
        return {
            "symbols": ["BTC/USDC"],
            "symbol_count": 1,
            "row_count": 2,
        }

    def fake_parse_csv_rows(_csv_content: str, _quote_currency: str):
        return {
            "BTC/USDC": [
                {
                    "timestamp": 1_760_000_000_000,
                    "price": 117644.41,
                    "amount": 0.00099153,
                },
                {"timestamp": 1_760_000_300_000, "price": 112170.19, "amount": 0.03863},
            ]
        }

    plugin.import_service = types.SimpleNamespace(
        import_from_csv=fake_import_from_csv,
        _parse_csv_rows=fake_parse_csv_rows,
    )

    async def fake_add_history_data_for_symbol(**kwargs):
        history_calls.append(kwargs)
        return True

    plugin.data = types.SimpleNamespace(
        add_history_data_for_symbol=fake_add_history_data_for_symbol
    )

    async def fake_sleep(_seconds: float) -> None:
        plugin.status = False

    monkeypatch.setattr(csv_signal_module.asyncio, "sleep", fake_sleep)

    await plugin.run(
        {
            "currency": "USDC",
            "tp": 1.0,
            "timeframe": "5m",
            "signal_settings": '{"csv_source":"/tmp/trades.csv"}',
        }
    )

    assert len(imported) == 1
    assert len(history_calls) == 1
    assert history_calls[0]["symbol"] == "BTC/USDC"
    assert history_calls[0]["since_ms"] == 1_759_999_700_000
    assert watcher_queue.get_nowait() == ["BTC/USDC"]


@pytest.mark.asyncio
async def test_csv_signal_prefills_history_from_parsed_first_row(monkeypatch) -> None:
    watcher_queue: asyncio.Queue[list[str]] = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)

    monkeypatch.setattr(csv_signal_module.model, "OpenTrades", _DummyOpenTradesZero)

    async def fake_load_csv_content(_source: str) -> str:
        return (
            "date;symbol;price;amount\n"
            "18/08/2025 19:32:00;BTC/USDC;117644.41;0.00099153\n"
            "24/08/2025 15:04:00;BTC/USDC;112170.19;0.03863000\n"
        )

    monkeypatch.setattr(plugin, "_load_csv_content", fake_load_csv_content)

    history_calls = []

    async def fake_import_from_csv(**kwargs):
        plugin.status = False
        return {"symbols": ["BTC/USDC"], "symbol_count": 1, "row_count": 2}

    def fake_parse_csv_rows(_csv_content: str, _quote_currency: str):
        return {
            "BTC/USDC": [
                {
                    "timestamp": 1_760_000_000_000,
                    "price": 117644.41,
                    "amount": 0.00099153,
                },
                {"timestamp": 1_760_000_300_000, "price": 112170.19, "amount": 0.03863},
            ]
        }

    plugin.import_service = types.SimpleNamespace(
        import_from_csv=fake_import_from_csv,
        _parse_csv_rows=fake_parse_csv_rows,
    )

    async def fake_add_history_data_for_symbol(**kwargs):
        history_calls.append(kwargs)
        return True

    plugin.data = types.SimpleNamespace(
        add_history_data_for_symbol=fake_add_history_data_for_symbol
    )

    async def fake_sleep(_seconds: float) -> None:
        plugin.status = False

    monkeypatch.setattr(csv_signal_module.asyncio, "sleep", fake_sleep)

    await plugin.run(
        {
            "currency": "USDC",
            "tp": 1.0,
            "timeframe": "15m",
            "signal_settings": '{"csv_source":"/tmp/trades.csv"}',
        }
    )

    assert len(history_calls) == 1
    assert history_calls[0]["since_ms"] == 1759999100000
    assert watcher_queue.get_nowait() == ["BTC/USDC"]


@pytest.mark.asyncio
async def test_csv_signal_skips_import_when_open_trades_exist(monkeypatch) -> None:
    watcher_queue: asyncio.Queue[list[str]] = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)

    monkeypatch.setattr(csv_signal_module.model, "OpenTrades", _DummyOpenTradesOne)

    async def fake_import_from_csv(**kwargs):
        raise AssertionError("Import should be skipped when open trades exist.")

    plugin.import_service = types.SimpleNamespace(import_from_csv=fake_import_from_csv)

    async def fake_sleep(_seconds: float) -> None:
        plugin.status = False

    monkeypatch.setattr(csv_signal_module.asyncio, "sleep", fake_sleep)

    await plugin.run(
        {
            "currency": "USDC",
            "tp": 1.0,
            "signal_settings": '{"csv_source":"/tmp/trades.csv"}',
        }
    )

    assert watcher_queue.empty()


@pytest.mark.asyncio
async def test_csv_signal_blocks_import_when_history_prefill_fails(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model

    watcher_queue: asyncio.Queue[list[str]] = asyncio.Queue()
    plugin = SignalPlugin(watcher_queue)

    async def fake_load_csv_content(_source: str) -> str:
        return (
            "date;symbol;price;amount\n"
            "18/08/2025 19:32:00;BTC/USDC;117644.41;0.00099153\n"
            "24/08/2025 15:04:00;BTC/USDC;112170.19;0.03863000\n"
        )

    monkeypatch.setattr(plugin, "_load_csv_content", fake_load_csv_content)

    events: list[str] = []

    async def fake_add_history_data_for_symbol(**_kwargs):
        events.append("prefill")
        return False

    async def fake_close() -> None:
        return None

    plugin.data = types.SimpleNamespace(
        add_history_data_for_symbol=fake_add_history_data_for_symbol,
        close=fake_close,
    )

    original_import_from_csv = plugin.import_service.import_from_csv

    async def tracked_import_from_csv(**kwargs):
        events.append("import")
        return await original_import_from_csv(**kwargs)

    plugin.import_service.import_from_csv = tracked_import_from_csv

    async def fake_sleep(_seconds: float) -> None:
        plugin.status = False

    monkeypatch.setattr(csv_signal_module.asyncio, "sleep", fake_sleep)

    try:
        await plugin.run(
            {
                "currency": "USDC",
                "tp": 1.0,
                "timeframe": "5m",
                "signal_settings": '{"csv_source":"/tmp/trades.csv"}',
            }
        )

        assert events == ["prefill"]
        assert await model.OpenTrades.all().count() == 0
        assert await model.Trades.all().count() == 0
        assert watcher_queue.empty()
    finally:
        await Tortoise.close_connections()
