import os
from datetime import datetime, timezone

import pytest
import service.backup_restore as backup_module
import service.config as config_module
from service.backup_restore import BackupService
from service.config import Config
from tortoise import Tortoise


class DummyRedis:
    async def publish(self, _channel, _message) -> int:
        return 1


async def _fake_config_instance(cls) -> Config:
    if cls._instance is None:
        cls._instance = Config()
    return cls._instance


@pytest.mark.asyncio
async def test_restore_backup_full_restores_trade_tables_and_clears_tickers(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())
    monkeypatch.setattr(Config, "instance", classmethod(_fake_config_instance))
    Config._instance = None

    import model

    await model.AppConfig.create(
        key="timezone", value="Europe/Vienna", value_type="str"
    )
    await model.AppConfig.create(key="tp", value="1.5", value_type="float")
    await model.Trades.create(
        timestamp="1",
        ordersize=10.0,
        fee=0.001,
        precision=3,
        amount=1.0,
        amount_fee=0.0,
        price=10.0,
        symbol="ABC/USDT",
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
    await model.OpenTrades.create(
        symbol="ABC/USDT",
        amount=1.0,
        cost=10.0,
        current_price=11.0,
        avg_price=10.0,
        open_date="1",
    )
    await model.ClosedTrades.create(
        symbol="XYZ/USDT",
        deal_id="44444444-4444-4444-4444-444444444444",
        so_count=0,
        profit=1.0,
        profit_percent=10.0,
        amount=1.0,
        cost=10.0,
        tp_price=11.0,
        avg_price=10.0,
        open_date="1",
        close_date="2",
        duration="{}",
    )
    await model.UnsellableTrades.create(
        symbol="DUST/USDT",
        amount=0.01,
        cost=0.05,
        current_price=4.0,
        avg_price=5.0,
        open_date="1",
        unsellable_reason="minimum_notional",
        unsellable_min_notional=5.0,
        unsellable_estimated_notional=0.04,
        unsellable_since="2026-03-17T12:00:00",
    )
    await model.Autopilot.create(mode="low")
    await model.UpnlHistory.create(
        timestamp=datetime.now(timezone.utc),
        upnl=1.0,
        profit_overall=2.0,
        funds_locked=3.0,
    )
    await model.Tickers.create(
        timestamp="1",
        symbol="ABC/USDT",
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        volume=100.0,
    )
    await model.TradeReplayCandles.create(
        deal_id="44444444-4444-4444-4444-444444444444",
        symbol="XYZ/USDT",
        timestamp="2",
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        volume=100.0,
    )

    backup_service = BackupService()
    backup_payload = await backup_service.export_backup(include_trade_data=True)

    await model.AppConfig.all().delete()
    await model.Trades.all().delete()
    await model.OpenTrades.all().delete()
    await model.ClosedTrades.all().delete()
    await model.UnsellableTrades.all().delete()
    await model.Autopilot.all().delete()
    await model.UpnlHistory.all().delete()
    await model.Tickers.all().delete()
    await model.Tickers.create(
        timestamp="2",
        symbol="SHOULD/CLEAR",
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=1.0,
    )

    history_refresh_calls: list[tuple[str, int, str | None]] = []

    async def fake_add_history_data_for_symbol(
        self,
        symbol: str,
        history_data: int,
        config: dict,
        since_ms=None,
    ) -> bool:
        del since_ms
        history_refresh_calls.append((symbol, history_data, config.get("timezone")))
        return True

    async def fake_close(self) -> None:
        return None

    monkeypatch.setattr(
        backup_module.Data,
        "add_history_data_for_symbol",
        fake_add_history_data_for_symbol,
    )
    monkeypatch.setattr(backup_module.Data, "close", fake_close)

    summary = await backup_service.restore_backup(
        backup_payload,
        restore_trade_data=True,
    )

    restored_config = await model.AppConfig.filter(key="timezone").first()
    assert restored_config is not None
    assert restored_config.value == "Europe/Vienna"
    assert await model.Trades.all().count() == 1
    assert await model.OpenTrades.all().count() == 1
    assert await model.ClosedTrades.all().count() == 1
    assert await model.TradeReplayCandles.all().count() == 1
    assert await model.UnsellableTrades.all().count() == 1
    assert await model.Autopilot.all().count() == 1
    assert await model.UpnlHistory.all().count() == 1
    assert await model.Tickers.all().count() == 0
    assert summary["history_refreshed_symbols"] == ["ABC/USDT"]
    assert summary["history_failed_symbols"] == []
    assert history_refresh_calls == [("ABC/USDT", 30, "Europe/Vienna")]

    await Tortoise.close_connections()
    Config._instance = None


@pytest.mark.asyncio
async def test_restore_backup_config_only_keeps_existing_trade_rows(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())
    monkeypatch.setattr(Config, "instance", classmethod(_fake_config_instance))
    Config._instance = None

    import model

    await model.AppConfig.create(key="timezone", value="UTC", value_type="str")
    await model.Trades.create(
        timestamp="1",
        ordersize=10.0,
        fee=0.001,
        precision=3,
        amount=1.0,
        amount_fee=0.0,
        price=10.0,
        symbol="KEEP/USDT",
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

    backup_service = BackupService()
    backup_payload = await backup_service.export_backup(include_trade_data=False)

    await model.AppConfig.filter(key="timezone").update(value="Europe/London")

    summary = await backup_service.restore_backup(
        backup_payload,
        restore_trade_data=False,
    )

    restored_config = await model.AppConfig.filter(key="timezone").first()
    assert restored_config is not None
    assert restored_config.value == "UTC"
    assert await model.Trades.all().count() == 1
    assert summary["history_refreshed_symbols"] == []
    assert summary["history_failed_symbols"] == []

    await Tortoise.close_connections()
    Config._instance = None


@pytest.mark.asyncio
async def test_export_backup_omits_removed_legacy_autopilot_max_fund_key(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())

    import model

    await model.AppConfig.create(
        key="autopilot_max_fund", value="250", value_type="int"
    )
    await model.AppConfig.create(key="capital_max_fund", value="300", value_type="int")

    backup_service = BackupService()
    backup_payload = await backup_service.export_backup(include_trade_data=False)

    assert len(backup_payload["config"]) == 1
    assert backup_payload["config"][0]["id"] == 2
    assert backup_payload["config"][0]["key"] == "capital_max_fund"
    assert backup_payload["config"][0]["value"] == "300"
    assert backup_payload["config"][0]["value_type"] == "int"

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_restore_backup_rejects_removed_legacy_autopilot_max_fund_key(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    monkeypatch.setattr(config_module, "redis_client", DummyRedis())
    monkeypatch.setattr(Config, "instance", classmethod(_fake_config_instance))
    Config._instance = None

    backup_service = BackupService()
    with pytest.raises(
        ValueError,
        match=(
            "Config key 'autopilot_max_fund' was removed in v1.4.0.0. "
            "Use 'capital_max_fund' instead."
        ),
    ):
        await backup_service.restore_backup(
            {
                "schema_version": 1,
                "config": [
                    {
                        "key": "autopilot_max_fund",
                        "value": "250",
                        "value_type": "int",
                    }
                ],
            },
            restore_trade_data=False,
        )

    await Tortoise.close_connections()
    Config._instance = None
