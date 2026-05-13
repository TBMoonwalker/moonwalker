import os
from datetime import datetime, timezone

import model
import pytest
from service.dca import Dca
from service.order_persistence import persist_closed_trade
from service.spot_campaign_types import SpotCampaignState, TradeCloseReason
from service.spot_sidestep_campaign import SpotSidestepCampaignService
from tortoise import Tortoise


class _DummySidestepCampaignService:
    def is_enabled(self, _config) -> bool:
        return True

    async def ensure_campaign_for_open_trade(self, _trade_data, _config):
        return "campaign-1"


def test_sidestep_campaign_service_only_enables_on_spot_market() -> None:
    assert (
        SpotSidestepCampaignService.is_enabled(
            {
                "sidestep_campaign_enabled": True,
                "market": "spot",
            }
        )
        is True
    )
    assert (
        SpotSidestepCampaignService.is_enabled(
            {
                "sidestep_campaign_enabled": True,
                "market": "future",
            }
        )
        is False
    )


@pytest.mark.asyncio
async def test_process_ticker_data_uses_bearish_sidestep_exit_before_dca(
    monkeypatch,
) -> None:
    dca = Dca()
    dispatched_orders: list[dict[str, object]] = []

    async def fake_get_trades_for_orders(_symbol: str):
        return {
            "timestamp": "1000",
            "fee": 0.0,
            "total_cost": 100.0,
            "total_amount": 1.0,
            "symbol": "BTC/USDT",
            "direction": "long",
            "side": "buy",
            "bot": "asap_BTC/USDT",
            "bo_price": 100.0,
            "current_price": 95.0,
            "safetyorders": [],
            "safetyorders_count": 0,
            "ordertype": "market",
            "campaign_id": None,
            "is_unsellable": False,
        }

    async def fake_get_profit():
        return {"funds_locked": 100.0}

    async def fake_resolve_trading_policy(_symbol, _funds_locked, _config):
        return type(
            "Policy",
            (),
            {
                "take_profit": 10.0,
                "stop_loss": 50.0,
                "stop_loss_timeout": 0,
                "mode": "none",
                "adaptive_tp_applied": False,
                "adaptive_reason_code": None,
                "adaptive_trust_score": None,
                "baseline_take_profit": 10.0,
            },
        )()

    async def fake_receive_sell_order(order, _config):
        dispatched_orders.append(dict(order))

    async def fake_should_sell(_symbol: str) -> bool:
        return True

    async def fail_calculate_dca(*_args, **_kwargs):
        raise AssertionError("sidestep exit should skip DCA")

    async def fail_calculate_tp(*_args, **_kwargs):
        raise AssertionError("sidestep exit should skip TP")

    async def fake_get_sidestep_campaigns():
        return _DummySidestepCampaignService()

    monkeypatch.setattr(
        dca.trades,
        "get_trades_for_orders",
        fake_get_trades_for_orders,
    )
    monkeypatch.setattr(dca.statistic, "get_profit", fake_get_profit)
    monkeypatch.setattr(
        dca.autopilot,
        "resolve_trading_policy",
        fake_resolve_trading_policy,
    )
    monkeypatch.setattr(dca.orders, "receive_sell_order", fake_receive_sell_order)
    monkeypatch.setattr(dca, "_Dca__sidestep_exit_strategy", fake_should_sell)
    monkeypatch.setattr(dca, "_Dca__calculate_dca", fail_calculate_dca)
    monkeypatch.setattr(dca, "_Dca__calculate_tp", fail_calculate_tp)
    monkeypatch.setattr(dca, "_get_sidestep_campaigns", fake_get_sidestep_campaigns)

    await dca.process_ticker_data(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDT", "price": 95.0}},
        {
            "dca": True,
            "sidestep_campaign_enabled": True,
            "sidestep_bearish_strategy": "ema_down",
            "tp": 10.0,
        },
    )

    assert len(dispatched_orders) == 1
    order = dispatched_orders[0]
    assert order["symbol"] == "BTC/USDT"
    assert order["direction"] == "long"
    assert order["side"] == "sell"
    assert order["sell_reason"] == "sidestep_exit"
    assert order["campaign_id"] == "campaign-1"
    assert order["actual_pnl"] == pytest.approx(-5.0)
    assert order["tp_price"] == pytest.approx(110.0)


@pytest.mark.asyncio
async def test_process_ticker_data_logs_waiting_statistics_for_flat_sidestep_trade(
    monkeypatch,
) -> None:
    dca = Dca()
    updated_rows: list[dict[str, object]] = []
    statistic_payloads: list[dict[str, object]] = []

    async def fake_get_trades_for_orders(_symbol: str):
        return {
            "symbol": "BTC/USDT",
            "bot": "asap_BTC/USDT",
            "campaign_id": "campaign-1",
            "lifecycle_mode": "sidestep_reentry",
            "exposure_state": "flat_waiting_reentry",
            "waiting_reference_amount": 1.0,
            "waiting_reference_quote": 120.0,
            "waiting_reference_price": 120.0,
            "reserved_reentry_quote": 120.0,
        }

    async def fake_update_open_trades(payload, symbol):
        updated_rows.append({"payload": dict(payload), "symbol": symbol})

    async def fake_update_statistic_data(payload):
        statistic_payloads.append(dict(payload))

    async def fail_waiting_reentry(*_args, **_kwargs):
        return False

    async def fake_get_sidestep_campaigns():
        return _DummySidestepCampaignService()

    monkeypatch.setattr(
        dca.trades,
        "get_trades_for_orders",
        fake_get_trades_for_orders,
    )
    monkeypatch.setattr(dca.trades, "update_open_trades", fake_update_open_trades)
    monkeypatch.setattr(
        dca.statistic,
        "update_statistic_data",
        fake_update_statistic_data,
    )
    monkeypatch.setattr(dca, "_Dca__attempt_waiting_reentry", fail_waiting_reentry)
    monkeypatch.setattr(dca, "_get_sidestep_campaigns", fake_get_sidestep_campaigns)

    await dca.process_ticker_data(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDT", "price": 100.0}},
        {
            "trade_lifecycle_mode": "sidestep_reentry",
            "market": "spot",
        },
    )

    assert len(updated_rows) == 1
    updated_payload = updated_rows[0]["payload"]
    assert updated_rows[0]["symbol"] == "BTC/USDT"
    assert updated_payload["virtual_waiting_profit"] == pytest.approx(20.0)
    assert updated_payload["virtual_waiting_profit_percent"] == pytest.approx(
        16.666666666666664
    )

    assert len(statistic_payloads) == 1
    statistic_payload = statistic_payloads[0]
    assert statistic_payload["type"] == "waiting_check"
    assert statistic_payload["symbol"] == "BTC/USDT"
    assert statistic_payload["botname"] == "asap_BTC/USDT"
    assert statistic_payload["current_price"] == pytest.approx(100.0)
    assert statistic_payload["waiting_reference_price"] == pytest.approx(120.0)
    assert statistic_payload["waiting_reference_amount"] == pytest.approx(1.0)
    assert statistic_payload["waiting_reference_quote"] == pytest.approx(120.0)
    assert statistic_payload["virtual_waiting_profit"] == pytest.approx(20.0)
    assert statistic_payload["virtual_waiting_profit_percent"] == pytest.approx(
        16.666666666666664
    )
    assert statistic_payload["reserved_reentry_quote"] == pytest.approx(120.0)
    assert statistic_payload["campaign_id"] == "campaign-1"
    assert statistic_payload["lifecycle_mode"] == "sidestep_reentry"
    assert statistic_payload["exposure_state"] == "flat_waiting_reentry"


@pytest.mark.asyncio
async def test_process_ticker_data_logs_sidestep_gate_without_active_trade(
    monkeypatch,
) -> None:
    dca = Dca()
    debug_calls: list[tuple[object, ...]] = []

    async def fake_get_trades_for_orders(_symbol: str):
        return None

    monkeypatch.setattr(
        dca.trades,
        "get_trades_for_orders",
        fake_get_trades_for_orders,
    )
    monkeypatch.setattr(
        "service.dca.logging.debug",
        lambda *args, **kwargs: debug_calls.append(args),
    )

    await dca.process_ticker_data(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDT", "price": 100.0}},
        {
            "trade_lifecycle_mode": "sidestep_reentry",
            "market": "spot",
        },
    )

    assert len(debug_calls) == 1
    assert debug_calls[0][0] == "Sidestep gate: %s"
    assert debug_calls[0][1] == {
        "symbol": "BTC/USDT",
        "sidestep_gate": "no_active_trade",
        "source": "watcher_symbol_only",
    }


@pytest.mark.asyncio
async def test_attempt_waiting_reentry_uses_reserved_quote_from_waiting_trade(
    monkeypatch,
) -> None:
    dca = Dca()
    submitted_orders: list[dict[str, object]] = []

    class _CampaignService:
        async def get_campaign_snapshot(self, _campaign_id: str):
            return {
                "campaign_id": "campaign-1",
                "reserved_quote": 50.0,
                "cooldown_until": None,
            }

    async def fake_get_sidestep_campaigns():
        return _CampaignService()

    async def fake_reentry_strategy(_symbol: str) -> bool:
        return True

    async def fake_receive_buy_order(order, _config):
        submitted_orders.append(dict(order))
        return True

    monkeypatch.setattr(dca, "_get_sidestep_campaigns", fake_get_sidestep_campaigns)
    monkeypatch.setattr(dca, "_Dca__sidestep_reentry_strategy", fake_reentry_strategy)
    monkeypatch.setattr(dca.orders, "receive_buy_order", fake_receive_buy_order)

    dca.config = {
        "trade_lifecycle_mode": "sidestep_reentry",
        "market": "spot",
        "sidestep_reentry_strategy": "ema20_swing",
        "timeframe": "4h",
        "bo": 25.0,
    }

    success = await dca._Dca__attempt_waiting_reentry(
        {
            "symbol": "ETH/USDT",
            "bot": "sidestep_ETH/USDT",
            "campaign_id": "campaign-1",
            "lifecycle_mode": "sidestep_reentry",
            "exposure_state": "flat_waiting_reentry",
            "reserved_reentry_quote": 112.5,
        },
        current_price=100.0,
    )

    assert success is True
    assert len(submitted_orders) == 1
    assert submitted_orders[0]["ordersize"] == pytest.approx(112.5)
    assert submitted_orders[0]["campaign_id"] == "campaign-1"
    assert submitted_orders[0]["strategy_name"] == "ema20_swing"


@pytest.mark.asyncio
async def test_process_ticker_data_logs_exit_tp_gate_before_bearish_strategy(
    monkeypatch,
) -> None:
    dca = Dca()
    debug_calls: list[tuple[object, ...]] = []

    async def fake_get_trades_for_orders(_symbol: str):
        return {
            "timestamp": "1000",
            "fee": 0.0,
            "total_cost": 100.0,
            "total_amount": 1.0,
            "symbol": "BTC/USDT",
            "direction": "long",
            "side": "buy",
            "bot": "asap_BTC/USDT",
            "bo_price": 100.0,
            "current_price": 111.0,
            "safetyorders": [],
            "safetyorders_count": 0,
            "ordertype": "market",
            "campaign_id": "campaign-1",
            "lifecycle_mode": "sidestep_reentry",
            "exposure_state": "long_exposed",
            "is_unsellable": False,
        }

    async def fake_get_profit():
        return {"funds_locked": 100.0}

    async def fake_resolve_trading_policy(_symbol, _funds_locked, _config):
        return type(
            "Policy",
            (),
            {
                "take_profit": 10.0,
                "stop_loss": 50.0,
                "stop_loss_timeout": 0,
                "mode": "none",
                "adaptive_tp_applied": False,
                "adaptive_reason_code": None,
                "adaptive_trust_score": None,
                "baseline_take_profit": 10.0,
            },
        )()

    async def fail_sidestep_strategy(_symbol: str) -> bool:
        raise AssertionError("sidestep strategy should not run above TP")

    async def fake_get_sidestep_campaigns():
        return _DummySidestepCampaignService()

    async def fake_calculate_tp(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        dca.trades,
        "get_trades_for_orders",
        fake_get_trades_for_orders,
    )
    monkeypatch.setattr(dca.statistic, "get_profit", fake_get_profit)
    monkeypatch.setattr(
        dca.autopilot,
        "resolve_trading_policy",
        fake_resolve_trading_policy,
    )
    monkeypatch.setattr(dca, "_Dca__sidestep_exit_strategy", fail_sidestep_strategy)
    monkeypatch.setattr(dca, "_Dca__calculate_tp", fake_calculate_tp)
    monkeypatch.setattr(dca, "_get_sidestep_campaigns", fake_get_sidestep_campaigns)
    monkeypatch.setattr(
        "service.dca.logging.debug",
        lambda *args, **kwargs: debug_calls.append(args),
    )

    await dca.process_ticker_data(
        {"type": "ticker_price", "ticker": {"symbol": "BTC/USDT", "price": 111.0}},
        {
            "trade_lifecycle_mode": "sidestep_reentry",
            "market": "spot",
            "tp": 10.0,
        },
    )

    assert len(debug_calls) == 1
    assert debug_calls[0][0] == "Sidestep gate: %s"
    assert debug_calls[0][1] == {
        "symbol": "BTC/USDT",
        "sidestep_gate": "exit_tp_gate",
        "current_price": 111.0,
        "tp_price": 110.0,
    }


@pytest.mark.asyncio
async def test_persist_closed_trade_infers_legacy_campaign_principal_quote(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    campaign_id = "campaign-legacy-principal"
    await model.SpotCampaigns.create(
        campaign_id=campaign_id,
        symbol="BTC/USDT",
        state=SpotCampaignState.ACTIVE_LONG.value,
        started_at="2026-05-01T00:00:00+00:00",
        last_transition_at="2026-05-01T00:00:00+00:00",
        current_deal_id="deal-legacy-1",
        sidestep_count=1,
        tp_percent=5.0,
        principal_quote=0.0,
        reserved_quote=0.0,
        cumulative_realized_quote=10.0,
        cumulative_realized_percent=0.0,
        metadata_json="{}",
    )
    await model.OpenTrades.create(
        symbol="BTC/USDT",
        deal_id="deal-legacy-1",
        campaign_id=campaign_id,
        lifecycle_mode="sidestep_reentry",
        exposure_state="long_exposed",
        execution_history_complete=True,
    )

    service = SpotSidestepCampaignService()
    closed_at = datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc)
    payload = {
        "symbol": "BTC/USDT",
        "profit": 5.0,
        "profit_percent": 4.545454545454546,
        "amount": 1.0,
        "cost": 110.0,
        "tp_price": 115.0,
        "avg_price": 110.0,
        "open_date": "2026-05-01 00:00:00+00:00",
        "close_date": "2026-05-02 12:00:00+00:00",
        "duration": "{}",
        "close_reason": TradeCloseReason.TAKE_PROFIT.value,
        "sell_executions": [],
    }

    context = await service.resolve_close_context(
        "BTC/USDT",
        TradeCloseReason.TAKE_PROFIT.value,
        {"tp": 5.0},
        closed_at=closed_at,
        closed_payload=payload,
    )

    assert context["principal_quote"] == pytest.approx(100.0)
    assert context["summary_overrides"]["profit_percent"] == pytest.approx(15.0)

    async def _noop_archive(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "service.order_persistence.archive_replay_candles_for_deal",
        _noop_archive,
    )
    await persist_closed_trade("BTC/USDT", payload, campaign_context=context)

    closed_trade = await model.ClosedTrades.get(symbol="BTC/USDT")
    assert closed_trade.profit == pytest.approx(15.0)
    assert closed_trade.profit_percent == pytest.approx(15.0)
    assert closed_trade.cost == pytest.approx(100.0)

    campaign = await model.SpotCampaigns.get(campaign_id=campaign_id)
    assert campaign.principal_quote == pytest.approx(100.0)

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_stop_campaign_infers_legacy_waiting_principal_quote(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    campaign_id = "campaign-legacy-stop"
    await model.SpotCampaigns.create(
        campaign_id=campaign_id,
        symbol="ETH/USDT",
        state=SpotCampaignState.FLAT_WAITING_REENTRY.value,
        started_at="2026-05-01T00:00:00+00:00",
        last_transition_at="2026-05-01T06:00:00+00:00",
        current_deal_id=None,
        sidestep_count=1,
        last_exit_reason=TradeCloseReason.SIDESTEP_EXIT.value,
        cooldown_until=None,
        tp_percent=5.0,
        principal_quote=0.0,
        reserved_quote=110.0,
        cumulative_realized_quote=10.0,
        cumulative_realized_percent=0.0,
        metadata_json="{}",
    )
    await model.OpenTrades.create(
        symbol="ETH/USDT",
        campaign_id=campaign_id,
        lifecycle_mode="sidestep_reentry",
        exposure_state="flat_waiting_reentry",
    )

    service = SpotSidestepCampaignService()
    stopped = await service.stop_campaign(campaign_id)

    assert stopped is True

    closed_trade = await model.ClosedTrades.get(symbol="ETH/USDT")
    assert closed_trade.profit == pytest.approx(10.0)
    assert closed_trade.profit_percent == pytest.approx(10.0)
    assert closed_trade.cost == pytest.approx(100.0)

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_activate_campaign_submits_manual_reentry_buy(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    campaign_id = "campaign-manual-activate"
    await model.SpotCampaigns.create(
        campaign_id=campaign_id,
        symbol="ETH/USDT",
        state=SpotCampaignState.FLAT_WAITING_REENTRY.value,
        started_at="2026-05-01T00:00:00+00:00",
        last_transition_at="2026-05-01T06:00:00+00:00",
        current_deal_id=None,
        sidestep_count=1,
        last_exit_reason=TradeCloseReason.SIDESTEP_EXIT.value,
        cooldown_until=None,
        tp_percent=5.0,
        principal_quote=100.0,
        reserved_quote=111.0,
        cumulative_realized_quote=10.0,
        cumulative_realized_percent=10.0,
        metadata_json="{}",
    )
    await model.OpenTrades.create(
        symbol="ETH/USDT",
        campaign_id=campaign_id,
        lifecycle_mode="sidestep_reentry",
        exposure_state="flat_waiting_reentry",
        reserved_reentry_quote=112.5,
    )

    submitted_orders: list[dict[str, object]] = []

    class _FakeOrders:
        async def receive_buy_order(self, order, config):
            submitted_orders.append({"order": dict(order), "config": dict(config)})
            return True

    service = SpotSidestepCampaignService()
    service.config = {
        "trade_lifecycle_mode": "sidestep_reentry",
        "market": "spot",
        "timeframe": "4h",
        "bo": 50.0,
    }
    service._orders = _FakeOrders()

    activated = await service.activate_campaign(campaign_id)

    assert activated is True
    assert len(submitted_orders) == 1
    submitted = submitted_orders[0]["order"]
    assert submitted["campaign_id"] == campaign_id
    assert submitted["symbol"] == "ETH/USDT"
    assert submitted["ordersize"] == pytest.approx(112.5)
    assert submitted["strategy_name"] == "manual_reentry"
    assert submitted["side"] == "buy"
    assert submitted["baseorder"] is True

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_ensure_campaign_for_open_trade_repairs_stale_runtime_state(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.SpotCampaigns.create(
        campaign_id="campaign-stale-open-trade",
        symbol="BTC/USDT",
        lifecycle_mode="classic_dca",
        state=SpotCampaignState.FLAT_WAITING_REENTRY.value,
        started_at="2026-05-01T00:00:00+00:00",
        last_transition_at="2026-05-02T00:00:00+00:00",
        current_deal_id="deal-stale-1",
        sidestep_count=1,
        tp_percent=5.0,
        principal_quote=100.0,
        reserved_quote=100.0,
        cumulative_realized_quote=0.0,
        cumulative_realized_percent=0.0,
        metadata_json="{}",
    )
    await model.OpenTrades.create(
        symbol="BTC/USDT",
        deal_id="deal-stale-1",
        campaign_id="campaign-stale-open-trade",
        lifecycle_mode="classic_dca",
        exposure_state="long_exposed",
        execution_history_complete=True,
    )

    service = SpotSidestepCampaignService()
    campaign_id = await service.ensure_campaign_for_open_trade(
        {"symbol": "BTC/USDT", "deal_id": "deal-stale-1"},
        {
            "trade_lifecycle_mode": "sidestep_reentry",
            "market": "spot",
        },
    )

    assert campaign_id == "campaign-stale-open-trade"
    open_trade = await model.OpenTrades.get(symbol="BTC/USDT")
    assert open_trade.lifecycle_mode == "sidestep_reentry"
    assert open_trade.exposure_state == "flat_waiting_reentry"

    campaign = await model.SpotCampaigns.get(campaign_id="campaign-stale-open-trade")
    assert campaign.lifecycle_mode == "sidestep_reentry"

    await Tortoise.close_connections()
