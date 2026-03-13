import os
from datetime import datetime, timedelta

import pytest
from service.housekeeper import Housekeeper
from tortoise import Tortoise


@pytest.mark.asyncio
async def test_housekeeper_deletes_only_old_inactive_symbol_rows(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model

    now = datetime.now()
    old_timestamp = str((now - timedelta(days=20)).timestamp())
    recent_timestamp = str((now - timedelta(days=1)).timestamp())

    await model.Trades.create(
        timestamp="1",
        ordersize=10.0,
        fee=0.001,
        precision=3,
        amount=1.0,
        amount_fee=0.0,
        price=10.0,
        symbol="ACTIVE/USDT",
        orderid="oid1",
        bot="bot",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
    )

    await model.Tickers.create(
        timestamp=old_timestamp,
        symbol="ACTIVE/USDT",
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10.0,
    )
    await model.Tickers.create(
        timestamp=old_timestamp,
        symbol="INACTIVE/USDT",
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10.0,
    )
    await model.Tickers.create(
        timestamp=recent_timestamp,
        symbol="INACTIVE/USDT",
        open=2.0,
        high=3.0,
        low=1.5,
        close=2.5,
        volume=10.0,
    )

    housekeeper = Housekeeper()
    deleted = await housekeeper._cleanup_inactive_ticker_history(now, retention_days=10)

    remaining = (
        await model.Tickers.all()
        .order_by("symbol", "timestamp")
        .values_list("symbol", "timestamp")
    )

    assert deleted == 1
    assert remaining == [
        ("ACTIVE/USDT", old_timestamp),
        ("INACTIVE/USDT", recent_timestamp),
    ]

    await Tortoise.close_connections()
