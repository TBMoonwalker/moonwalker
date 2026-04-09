import json
import os

import pytest
from service.data import Data
from service.replay_candles import archive_replay_candles_for_deal
from service.trades import Trades
from tortoise import Tortoise


async def _init_test_db(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()


def _make_candle(timestamp: int, close: float) -> list[float]:
    return [
        timestamp,
        close - 1.0,
        close + 1.0,
        close - 2.0,
        close,
        10.0,
    ]


@pytest.mark.asyncio
async def test_archive_replay_candles_for_closed_deal_persists_bounded_window(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_test_db(tmp_path, monkeypatch)

    import model
    import service.replay_candles as replay_module

    monkeypatch.setattr(replay_module, "REPLAY_ARCHIVE_PRE_ROLL_MS", 60_000)
    monkeypatch.setattr(replay_module, "REPLAY_ARCHIVE_POST_ROLL_MS", 120_000)

    deal_id = "11111111-1111-1111-1111-111111111111"
    symbol = "ABC/USDT"

    await model.TradeExecutions.create(
        deal_id=deal_id,
        symbol=symbol,
        side="buy",
        role="base_order",
        timestamp="120000",
        price=10.0,
        amount=1.0,
        ordersize=10.0,
        fee=0.0,
    )
    await model.TradeExecutions.create(
        deal_id=deal_id,
        symbol=symbol,
        side="sell",
        role="final_sell",
        timestamp="240000",
        price=11.0,
        amount=1.0,
        ordersize=11.0,
        fee=0.0,
    )

    for timestamp in (0, 60_000, 120_000, 180_000, 240_000, 300_000, 420_000):
        await model.Tickers.create(
            timestamp=str(timestamp),
            symbol=symbol,
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            volume=10.0,
        )

    archived = await archive_replay_candles_for_deal(
        deal_id,
        symbol,
        open_date="120000",
        close_date="240000",
    )

    archived_rows = await model.TradeReplayCandles.filter(deal_id=deal_id)
    archived_timestamps = sorted(int(row.timestamp) for row in archived_rows)

    assert archived == 5
    assert archived_timestamps == [60_000, 120_000, 180_000, 240_000, 300_000]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_data_service_reads_archived_replay_candles(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_test_db(tmp_path, monkeypatch)

    import model

    deal_id = "22222222-2222-2222-2222-222222222222"

    for timestamp, open_price, close_price in (
        (0, 9.0, 9.5),
        (60_000, 10.0, 10.5),
        (120_000, 10.5, 11.0),
        (180_000, 11.0, 11.5),
        (240_000, 11.5, 12.0),
    ):
        await model.TradeReplayCandles.create(
            deal_id=deal_id,
            symbol="ABC/USDT",
            timestamp=str(timestamp),
            open=open_price,
            high=open_price + 0.5,
            low=open_price - 0.5,
            close=close_price,
            volume=10.0,
        )

    data = Data()
    payload = await data.get_archived_ohlcv_for_deal(
        deal_id,
        "1m",
        60_000,
        180_000,
        0,
    )
    records = [payload] if isinstance(payload, dict) else json.loads(payload)

    assert [record["time"] for record in records] == [60.0, 120.0, 180.0]
    assert [record["open"] for record in records] == [10.0, 10.5, 11.0]

    await data.close()
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_archive_replay_candles_persists_live_close_candle(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_test_db(tmp_path, monkeypatch)

    import model
    import service.replay_candles as replay_module

    monkeypatch.setattr(replay_module, "REPLAY_ARCHIVE_PRE_ROLL_MS", 60_000)
    monkeypatch.setattr(replay_module, "REPLAY_ARCHIVE_POST_ROLL_MS", 120_000)
    monkeypatch.setattr(
        replay_module,
        "get_live_candle_snapshot",
        lambda _symbol: [240_000, 10.8, 11.3, 10.7, 11.1, 15.0],
    )

    deal_id = "2a2a2a2a-2222-4444-8888-222222222222"
    symbol = "ABC/USDT"

    await model.TradeExecutions.create(
        deal_id=deal_id,
        symbol=symbol,
        side="buy",
        role="base_order",
        timestamp="120000",
        price=10.0,
        amount=1.0,
        ordersize=10.0,
        fee=0.0,
    )
    await model.TradeExecutions.create(
        deal_id=deal_id,
        symbol=symbol,
        side="sell",
        role="final_sell",
        timestamp="240000",
        price=11.1,
        amount=1.0,
        ordersize=11.1,
        fee=0.0,
    )

    for timestamp, close_price in (
        (60_000, 9.8),
        (120_000, 10.0),
        (180_000, 10.6),
    ):
        await model.Tickers.create(
            timestamp=str(timestamp),
            symbol=symbol,
            open=close_price - 0.2,
            high=close_price + 0.2,
            low=close_price - 0.4,
            close=close_price,
            volume=10.0,
        )

    archived = await archive_replay_candles_for_deal(
        deal_id,
        symbol,
        open_date="120000",
        close_date="240000",
    )

    archived_rows = await model.TradeReplayCandles.filter(deal_id=deal_id).values(
        "timestamp", "close"
    )
    archived_rows.sort(key=lambda row: int(row["timestamp"]))

    assert archived == 4
    assert [int(row["timestamp"]) for row in archived_rows] == [
        60_000,
        120_000,
        180_000,
        240_000,
    ]
    assert archived_rows[-1]["close"] == 11.1

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_archive_replay_candles_repairs_existing_incomplete_archive(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_test_db(tmp_path, monkeypatch)

    import model
    import service.replay_candles as replay_module

    monkeypatch.setattr(replay_module, "REPLAY_ARCHIVE_PRE_ROLL_MS", 60_000)
    monkeypatch.setattr(replay_module, "REPLAY_ARCHIVE_POST_ROLL_MS", 120_000)
    monkeypatch.setattr(replay_module, "get_live_candle_snapshot", lambda _symbol: None)

    deal_id = "3b3b3b3b-3333-4444-8888-333333333333"
    symbol = "ABC/USDT"

    await model.TradeExecutions.create(
        deal_id=deal_id,
        symbol=symbol,
        side="buy",
        role="base_order",
        timestamp="120000",
        price=10.0,
        amount=1.0,
        ordersize=10.0,
        fee=0.0,
    )
    await model.TradeExecutions.create(
        deal_id=deal_id,
        symbol=symbol,
        side="sell",
        role="final_sell",
        timestamp="240000",
        price=11.1,
        amount=1.0,
        ordersize=11.1,
        fee=0.0,
    )

    for timestamp, close_price in (
        (60_000, 9.8),
        (120_000, 10.0),
        (180_000, 10.6),
        (240_000, 11.1),
    ):
        await model.Tickers.create(
            timestamp=str(timestamp),
            symbol=symbol,
            open=close_price - 0.2,
            high=close_price + 0.2,
            low=close_price - 0.4,
            close=close_price,
            volume=10.0,
        )

    for timestamp, close_price in (
        (60_000, 9.8),
        (120_000, 10.0),
        (180_000, 10.6),
    ):
        await model.TradeReplayCandles.create(
            deal_id=deal_id,
            symbol=symbol,
            timestamp=str(timestamp),
            open=close_price - 0.2,
            high=close_price + 0.2,
            low=close_price - 0.4,
            close=close_price,
            volume=10.0,
        )

    archived = await archive_replay_candles_for_deal(
        deal_id,
        symbol,
        open_date="120000",
        close_date="240000",
    )

    archived_rows = await model.TradeReplayCandles.filter(deal_id=deal_id).values(
        "timestamp", "close"
    )
    archived_rows.sort(key=lambda row: int(row["timestamp"]))

    assert archived == 4
    assert [int(row["timestamp"]) for row in archived_rows] == [
        60_000,
        120_000,
        180_000,
        240_000,
    ]
    assert archived_rows[-1]["close"] == 11.1

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_archive_replay_candles_repairs_sparse_archive_from_exchange_history(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_test_db(tmp_path, monkeypatch)

    import model
    import service.replay_candles as replay_module

    class _FakeConfig:
        def snapshot(self) -> dict[str, str]:
            return {"exchange": "binance", "timeframe": "4h"}

    class _FakeExchange:
        async def get_history_for_symbol(
            self,
            config: dict[str, str],
            symbol: str,
            timeframe: str,
            limit: int = 1,
            since: int = 0,
            until: int | None = None,
        ) -> list[list[float]]:
            assert config["exchange"] == "binance"
            assert symbol == "ABC/USDT"
            assert timeframe == "4h"
            assert since == 0
            assert until == 43_200_000
            return [
                _make_candle(0, 10.0),
                _make_candle(14_400_000, 11.0),
                _make_candle(28_800_000, 12.0),
                _make_candle(43_200_000, 13.0),
            ]

        async def close(self) -> None:
            return None

    async def _fake_config_instance() -> _FakeConfig:
        return _FakeConfig()

    monkeypatch.setattr(replay_module, "REPLAY_ARCHIVE_PRE_ROLL_MS", 0)
    monkeypatch.setattr(replay_module, "REPLAY_ARCHIVE_POST_ROLL_MS", 0)
    monkeypatch.setattr(replay_module, "get_live_candle_snapshot", lambda _symbol: None)
    monkeypatch.setattr(replay_module.Config, "instance", _fake_config_instance)
    monkeypatch.setattr(replay_module, "Exchange", _FakeExchange)

    deal_id = "4c4c4c4c-4444-4444-8888-444444444444"
    symbol = "ABC/USDT"

    await model.TradeExecutions.create(
        deal_id=deal_id,
        symbol=symbol,
        side="buy",
        role="base_order",
        timestamp="0",
        price=10.0,
        amount=1.0,
        ordersize=10.0,
        fee=0.0,
    )
    await model.TradeExecutions.create(
        deal_id=deal_id,
        symbol=symbol,
        side="sell",
        role="final_sell",
        timestamp="43200000",
        price=13.0,
        amount=1.0,
        ordersize=13.0,
        fee=0.0,
    )

    for timestamp, close_price in (
        (0, 10.0),
        (43_200_000, 13.0),
    ):
        await model.Tickers.create(
            timestamp=str(timestamp),
            symbol=symbol,
            open=close_price - 0.2,
            high=close_price + 0.2,
            low=close_price - 0.4,
            close=close_price,
            volume=10.0,
        )
        await model.TradeReplayCandles.create(
            deal_id=deal_id,
            symbol=symbol,
            timestamp=str(timestamp),
            open=close_price - 0.2,
            high=close_price + 0.2,
            low=close_price - 0.4,
            close=close_price,
            volume=10.0,
        )

    archived = await archive_replay_candles_for_deal(
        deal_id,
        symbol,
        open_date="0",
        close_date="43200000",
    )

    archived_rows = await model.TradeReplayCandles.filter(deal_id=deal_id).values(
        "timestamp"
    )
    archived_timestamps = sorted(int(row["timestamp"]) for row in archived_rows)

    assert archived == 4
    assert archived_timestamps == [0, 14_400_000, 28_800_000, 43_200_000]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_delete_closed_trade_cascades_archived_replay_candles(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _init_test_db(tmp_path, monkeypatch)

    import model

    deal_id = "33333333-3333-3333-3333-333333333333"
    closed_trade = await model.ClosedTrades.create(
        symbol="ABC/USDT",
        deal_id=deal_id,
        execution_history_complete=True,
        so_count=0,
        profit=1.0,
        profit_percent=10.0,
        amount=1.0,
        cost=10.0,
        tp_price=11.0,
        avg_price=10.0,
        open_date="120000",
        close_date="240000",
        duration="{}",
    )
    await model.TradeExecutions.create(
        deal_id=deal_id,
        symbol="ABC/USDT",
        side="sell",
        role="final_sell",
        timestamp="240000",
        price=11.0,
        amount=1.0,
        ordersize=11.0,
        fee=0.0,
    )
    await model.TradeReplayCandles.create(
        deal_id=deal_id,
        symbol="ABC/USDT",
        timestamp="180000",
        open=10.0,
        high=11.0,
        low=9.5,
        close=10.5,
        volume=10.0,
    )

    deleted = await Trades().delete_closed_trade(closed_trade.id)

    assert deleted is True
    assert await model.ClosedTrades.filter(deal_id=deal_id).count() == 0
    assert await model.TradeExecutions.filter(deal_id=deal_id).count() == 0
    assert await model.TradeReplayCandles.filter(deal_id=deal_id).count() == 0

    await Tortoise.close_connections()
