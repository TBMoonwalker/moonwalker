import os
from asyncio import CancelledError
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
    old_timestamp_seconds = str(int((now - timedelta(days=20)).timestamp()))
    old_timestamp_ms = str(int((now - timedelta(days=20)).timestamp() * 1000))
    recent_timestamp_ms = str(int((now - timedelta(days=1)).timestamp() * 1000))

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
        timestamp=old_timestamp_ms,
        symbol="ACTIVE/USDT",
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10.0,
    )
    await model.Tickers.create(
        timestamp=old_timestamp_ms,
        symbol="INACTIVE/USDT",
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10.0,
    )
    await model.Tickers.create(
        timestamp=old_timestamp_seconds,
        symbol="INACTIVE/USDT",
        open=1.1,
        high=2.1,
        low=0.6,
        close=1.6,
        volume=11.0,
    )
    await model.Tickers.create(
        timestamp=recent_timestamp_ms,
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

    assert deleted == 2
    assert remaining == [
        ("ACTIVE/USDT", old_timestamp_ms),
        ("INACTIVE/USDT", recent_timestamp_ms),
    ]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_housekeeper_shutdown_is_instance_local() -> None:
    first = Housekeeper()
    second = Housekeeper()

    await first.shutdown()

    assert first._running is False
    assert second._running is True


@pytest.mark.asyncio
async def test_housekeeper_cleanup_cycle_propagates_unexpected_errors(
    monkeypatch,
) -> None:
    housekeeper = Housekeeper()

    async def fail_unexpected(*_args, **_kwargs) -> int:
        raise TypeError("unexpected")

    monkeypatch.setattr(
        housekeeper,
        "_cleanup_inactive_ticker_history",
        fail_unexpected,
    )

    with pytest.raises(TypeError, match="unexpected"):
        await housekeeper._run_cleanup_cycle(datetime.now(), retention_days=10)


@pytest.mark.asyncio
async def test_housekeeper_cleanup_loop_keeps_running_on_recoverable_errors(
    monkeypatch,
) -> None:
    housekeeper = Housekeeper()
    housekeeper.config = {"timeframe": "1m"}
    calls = {"cleanup": 0, "sleep": 0}

    async def fail_recoverable(*_args, **_kwargs) -> None:
        calls["cleanup"] += 1
        raise RuntimeError("db busy")

    async def stop_after_first_sleep(_seconds: float) -> None:
        calls["sleep"] += 1
        raise CancelledError()

    monkeypatch.setattr(housekeeper, "_run_cleanup_cycle", fail_recoverable)
    monkeypatch.setattr("service.housekeeper.asyncio.sleep", stop_after_first_sleep)

    with pytest.raises(CancelledError):
        await housekeeper.cleanup_ticker_database()

    assert calls == {"cleanup": 1, "sleep": 1}
