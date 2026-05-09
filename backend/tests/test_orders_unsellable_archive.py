import os

import pytest
from service.orders import Orders
from tortoise import Tortoise


@pytest.mark.asyncio
async def test_receive_sell_order_archives_unsellable_remainder(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model

    await model.Trades.create(
        timestamp="1773580000000",
        ordersize=11.98,
        fee=0.001,
        precision=3,
        amount=5.13,
        amount_fee=0.0,
        price=2.335282651,
        symbol="LPT/USDC",
        orderid="oid1",
        bot="asap_LPT/USDC",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
    )
    await model.OpenTrades.create(
        symbol="LPT/USDC",
        so_count=0,
        amount=5.13,
        cost=11.98,
        current_price=2.274,
        avg_price=2.335282651,
        open_date="1773580000000",
    )

    orders = Orders()
    notified_events: list[tuple[str, dict]] = []

    async def fake_create_spot_sell(_order, _config):
        return {
            "type": "partial_sell",
            "symbol": "LPT/USDC",
            "partial_filled_amount": 5.12,
            "partial_proceeds": 11.64288,
            "remaining_amount": 0.01,
            "unsellable": True,
            "unsellable_reason": "minimum_notional",
            "unsellable_min_notional": 10.0,
            "unsellable_estimated_notional": 0.02274,
        }

    async def fake_close() -> None:
        return None

    async def fake_notify(event_type: str, payload: dict, _config: dict) -> None:
        notified_events.append((event_type, payload))

    monkeypatch.setattr(orders.exchange, "create_spot_sell", fake_create_spot_sell)
    monkeypatch.setattr(orders.exchange, "close", fake_close)
    monkeypatch.setattr(orders.monitoring, "notify_trade", fake_notify)

    await orders.receive_sell_order(
        {
            "symbol": "LPT/USDC",
            "direction": "long",
            "side": "sell",
            "type_sell": "order_sell",
            "actual_pnl": -2.84,
            "total_cost": 11.98,
            "current_price": 2.274,
        },
        {"tp": 1.0, "monitoring_enabled": True},
    )

    assert await model.OpenTrades.all().count() == 0
    assert await model.Trades.all().count() == 0

    closed_trade = await model.ClosedTrades.all().first()
    assert closed_trade is not None
    assert closed_trade.symbol == "LPT/USDC"
    assert closed_trade.amount == pytest.approx(5.12)
    assert closed_trade.cost == pytest.approx(11.95664717)

    unsellable_trade = await model.UnsellableTrades.all().first()
    assert unsellable_trade is not None
    assert unsellable_trade.symbol == "LPT/USDC"
    assert unsellable_trade.amount == pytest.approx(0.01)
    assert unsellable_trade.cost == pytest.approx(0.02335283)
    assert unsellable_trade.current_price == pytest.approx(2.274)
    assert unsellable_trade.unsellable_reason == "minimum_notional"
    assert unsellable_trade.unsellable_min_notional == pytest.approx(10.0)
    assert unsellable_trade.unsellable_estimated_notional == pytest.approx(0.02274)

    assert len(notified_events) == 1
    assert notified_events[0][0] == "trade.unsellable_notional"

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_receive_sell_order_keeps_sidestep_campaign_waiting_on_unsellable_dust(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    import model
    from service.spot_campaign_types import SpotCampaignState

    campaign_id = "campaign-btc-sidestep"
    await model.Trades.create(
        timestamp="1778299206806",
        ordersize=3834.16000000,
        fee=0.001,
        precision=5,
        amount=0.04768,
        amount_fee=0.0,
        price=80397.7,
        symbol="BTC/USDC",
        orderid="oid1",
        bot="sidestep_BTC/USDC",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
        campaign_id=campaign_id,
        deal_id="deal-btc-1",
    )
    await model.OpenTrades.create(
        symbol="BTC/USDC",
        deal_id="deal-btc-1",
        campaign_id=campaign_id,
        lifecycle_mode="sidestep_reentry",
        exposure_state="long_exposed",
        execution_history_complete=True,
        amount=0.04768,
        cost=3834.16000000,
        current_price=80397.7,
        avg_price=80410.73825503355,
        open_date="2026-05-09T04:00:06.806000+00:00",
    )
    await model.SpotCampaigns.create(
        campaign_id=campaign_id,
        symbol="BTC/USDC",
        lifecycle_mode="sidestep_reentry",
        state=SpotCampaignState.ACTIVE_LONG.value,
        started_at="2026-05-07T16:17:06.796000+00:00",
        last_transition_at="2026-05-09T04:00:08.169000+00:00",
        current_deal_id="deal-btc-1",
        sidestep_count=1,
        last_exit_reason=None,
        cooldown_until=None,
        tp_percent=5.0,
        principal_quote=3834.16000000,
        reserved_quote=0.0,
        cumulative_realized_quote=0.0,
        cumulative_realized_percent=0.0,
        metadata_json="{}",
    )

    async def _noop_archive(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "service.order_persistence.archive_replay_candles_for_deal",
        _noop_archive,
    )

    orders = Orders()
    notified_events: list[tuple[str, dict]] = []
    partial_amount = 0.0476753
    partial_price = 80397.7
    partial_proceeds = partial_amount * partial_price

    async def fake_create_spot_sell(_order, _config):
        return {
            "type": "partial_sell",
            "symbol": "BTC/USDC",
            "partial_filled_amount": partial_amount,
            "partial_avg_price": partial_price,
            "partial_proceeds": partial_proceeds,
            "remaining_amount": 0.0000047,
            "unsellable": True,
            "unsellable_reason": "minimum_notional",
            "unsellable_min_notional": 5.0,
            "unsellable_estimated_notional": 0.37700744500026573,
            "executions": [
                {
                    "symbol": "BTC/USDC",
                    "side": "sell",
                    "role": "final_sell",
                    "timestamp": "1778467225854",
                    "price": partial_price,
                    "amount": partial_amount,
                    "ordersize": partial_proceeds,
                    "fee": 0.0,
                    "order_id": "sell-btc-1",
                    "order_type": "market",
                }
            ],
        }

    async def fake_close() -> None:
        return None

    async def fake_notify(event_type: str, payload: dict, _config: dict) -> None:
        notified_events.append((event_type, payload))

    monkeypatch.setattr(orders.exchange, "create_spot_sell", fake_create_spot_sell)
    monkeypatch.setattr(orders.exchange, "close", fake_close)
    monkeypatch.setattr(orders.monitoring, "notify_trade", fake_notify)

    await orders.receive_sell_order(
        {
            "symbol": "BTC/USDC",
            "direction": "long",
            "side": "sell",
            "type_sell": "order_sell",
            "actual_pnl": 0.0,
            "total_cost": 3834.16000000,
            "current_price": partial_price,
            "sell_reason": "sidestep_exit",
            "campaign_id": campaign_id,
        },
        {"tp": 5.0, "monitoring_enabled": True},
    )

    open_trade = await model.OpenTrades.get(symbol="BTC/USDC")
    assert open_trade.campaign_id == campaign_id
    assert open_trade.deal_id is None
    assert open_trade.lifecycle_mode == "sidestep_reentry"
    assert open_trade.exposure_state == "flat_waiting_reentry"
    assert open_trade.amount == pytest.approx(0.0)
    assert open_trade.cost == pytest.approx(0.0)
    assert open_trade.reserved_reentry_quote == pytest.approx(partial_proceeds)
    assert open_trade.waiting_reference_amount == pytest.approx(partial_amount)
    assert open_trade.waiting_reference_quote == pytest.approx(partial_proceeds)

    campaign = await model.SpotCampaigns.get(campaign_id=campaign_id)
    assert campaign.state == "flat_waiting_reentry"
    assert campaign.current_deal_id is None
    assert campaign.last_exit_reason == "sidestep_exit"
    assert campaign.sidestep_count == 2
    assert campaign.reserved_quote == pytest.approx(partial_proceeds)

    assert await model.Trades.all().count() == 0
    assert await model.ClosedTrades.all().count() == 0

    unsellable_trade = await model.UnsellableTrades.get(symbol="BTC/USDC")
    assert unsellable_trade.deal_id == "deal-btc-1"
    assert unsellable_trade.amount == pytest.approx(0.0000047)
    assert unsellable_trade.unsellable_reason == "minimum_notional"

    assert len(notified_events) == 1
    assert notified_events[0][0] == "trade.unsellable_notional"

    await Tortoise.close_connections()
