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

    archived_rows = await model.TradeReplayCandles.filter(deal_id=deal_id).order_by(
        "timestamp"
    )
    archived_timestamps = [
        int(value) for value in await archived_rows.values_list("timestamp", flat=True)
    ]

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
        (60_000, 10.0, 10.5),
        (120_000, 10.5, 11.0),
        (180_000, 11.0, 11.5),
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
    payload = await data.get_archived_ohlcv_for_deal(deal_id, "1m", 0)
    records = json.loads(payload)

    assert [record["time"] for record in records] == [60.0, 120.0, 180.0]
    assert [record["open"] for record in records] == [10.0, 10.5, 11.0]

    await data.close()
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
