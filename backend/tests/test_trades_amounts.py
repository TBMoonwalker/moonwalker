import os

import model
import pytest
from service.spot_campaign_types import TradeCloseReason
from service.trades import Trades
from tortoise import Tortoise


@pytest.mark.asyncio
async def test_get_token_amount_from_trades_uses_net_amount(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.Trades.create(
        timestamp="1",
        ordersize=10.0,
        fee=0.001,
        precision=3,
        amount=99.0,
        amount_fee=1.0,
        price=0.1,
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

    trades = Trades()
    total_amount = await trades.get_token_amount_from_trades("ABC/USDT")

    assert total_amount == 99.0
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_trades_for_orders_uses_net_amount(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.Trades.create(
        timestamp="1",
        ordersize=10.0,
        fee=0.001,
        precision=3,
        amount=99.0,
        amount_fee=1.0,
        price=0.1,
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

    trades = Trades()
    aggregated = await trades.get_trades_for_orders("ABC/USDT")

    assert aggregated is not None
    assert aggregated["total_amount"] == 99.0
    assert aggregated["sellable_amount"] == 99.0
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_partial_sell_execution_reads_open_trade_totals(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.OpenTrades.create(
        symbol="ABC/USDT",
        sold_amount=1.25,
        sold_proceeds=126.5,
    )

    trades = Trades()
    sold_amount, sold_proceeds = await trades.get_partial_sell_execution("ABC/USDT")

    assert sold_amount == 1.25
    assert sold_proceeds == 126.5
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_token_amount_from_trades_subtracts_partial_sell_totals(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.Trades.create(
        timestamp="1",
        ordersize=12.1075,
        fee=0.001,
        precision=3,
        amount=725.0,
        amount_fee=0.0,
        price=0.0167,
        symbol="SENT/USDC",
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
        symbol="SENT/USDC",
        sold_amount=608.0,
        sold_proceeds=10.1536,
    )

    trades = Trades()
    total_amount = await trades.get_token_amount_from_trades("SENT/USDC")

    assert total_amount == pytest.approx(117.0)
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_trades_for_orders_exposes_remaining_sellable_amount_after_partial_sell(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.Trades.create(
        timestamp="1",
        ordersize=12.1075,
        fee=0.001,
        precision=3,
        amount=88.3,
        amount_fee=0.0,
        price=0.1372,
        symbol="ERA/USDC",
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
        symbol="ERA/USDC",
        sold_amount=76.6,
        sold_proceeds=10.50952,
    )

    trades = Trades()
    aggregated = await trades.get_trades_for_orders("ERA/USDC")

    assert aggregated is not None
    assert aggregated["total_amount"] == pytest.approx(88.3)
    assert aggregated["sellable_amount"] == pytest.approx(11.7)
    assert aggregated["total_cost"] == pytest.approx(12.1075)
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_trades_for_orders_uses_unsellable_open_trade_amounts(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.Trades.create(
        timestamp="1",
        ordersize=100.0,
        fee=0.001,
        precision=3,
        amount=1.0,
        amount_fee=0.0,
        price=100.0,
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
        amount=0.4,
        cost=42.0,
        current_price=120.0,
        unsellable_amount=0.4,
        unsellable_reason="minimum_notional",
        unsellable_min_notional=5.0,
        unsellable_estimated_notional=4.8,
    )

    trades = Trades()
    aggregated = await trades.get_trades_for_orders("ABC/USDT")

    assert aggregated is not None
    assert aggregated["is_unsellable"] is True
    assert aggregated["total_amount"] == 0.4
    assert aggregated["total_cost"] == 42.0
    assert aggregated["unsellable_reason"] == "minimum_notional"
    assert aggregated["unsellable_min_notional"] == 5.0
    assert aggregated["unsellable_estimated_notional"] == 4.8
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_trades_for_orders_returns_active_flat_waiting_context(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.OpenTrades.create(
        symbol="BTC/USDT",
        campaign_id="campaign-1",
        lifecycle_mode="sidestep_reentry",
        exposure_state="flat_waiting_reentry",
        current_price=95.0,
        reserved_reentry_quote=101.5,
        waiting_reference_price=101.5,
        waiting_reference_amount=1.0,
        waiting_reference_quote=101.5,
        virtual_waiting_profit=6.5,
        virtual_waiting_profit_percent=6.4,
        last_transition_at="2026-05-02T10:00:00+00:00",
    )

    trades = Trades()
    aggregated = await trades.get_trades_for_orders("BTC/USDT")

    assert aggregated is not None
    assert aggregated["campaign_id"] == "campaign-1"
    assert aggregated["lifecycle_mode"] == "sidestep_reentry"
    assert aggregated["exposure_state"] == "flat_waiting_reentry"
    assert aggregated["reserved_reentry_quote"] == 101.5
    assert aggregated["virtual_waiting_profit"] == 6.5
    assert aggregated["campaign_total_profit"] == 6.5
    assert aggregated["display_profit_percent"] == 6.4
    assert aggregated["total_amount"] == 0.0
    assert aggregated["total_cost"] == 0.0

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_waiting_trades_surfaces_campaign_status_fields(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.SpotCampaigns.create(
        campaign_id="campaign-waiting-status",
        symbol="BTC/USDT",
        lifecycle_mode="sidestep_reentry",
        state="flat_waiting_reentry",
        started_at="2026-05-01T00:00:00+00:00",
        last_transition_at="2026-05-02T10:00:00+00:00",
        current_deal_id=None,
        sidestep_count=2,
        last_exit_reason=TradeCloseReason.SIDESTEP_EXIT.value,
        cooldown_until="2099-05-02T12:00:00+00:00",
        tp_percent=5.0,
        principal_quote=101.5,
        reserved_quote=101.5,
        cumulative_realized_quote=4.0,
        cumulative_realized_percent=3.94,
        metadata_json='{"last_long_signal_at":"2026-05-02T11:00:00+00:00"}',
    )
    await model.OpenTrades.create(
        symbol="BTC/USDT",
        campaign_id="campaign-waiting-status",
        lifecycle_mode="sidestep_reentry",
        exposure_state="flat_waiting_reentry",
        current_price=95.0,
        reserved_reentry_quote=101.5,
        waiting_reference_price=101.5,
        waiting_reference_amount=1.0,
        waiting_reference_quote=101.5,
        virtual_waiting_profit=6.5,
        virtual_waiting_profit_percent=6.4,
        last_transition_at="2026-05-02T10:00:00+00:00",
    )

    trades = Trades()
    waiting_rows = await trades.get_waiting_trades()

    assert len(waiting_rows) == 1
    waiting_row = waiting_rows[0]
    assert waiting_row["last_exit_reason"] == TradeCloseReason.SIDESTEP_EXIT.value
    assert waiting_row["cooldown_until"] == "2099-05-02T12:00:00+00:00"
    assert waiting_row["last_long_signal_at"] == "2026-05-02T11:00:00+00:00"
    assert waiting_row["reentry_status"] == "Cooldown active"

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_trades_for_orders_repairs_waiting_runtime_from_campaign_state(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.SpotCampaigns.create(
        campaign_id="campaign-waiting-legacy",
        symbol="BTC/USDT",
        lifecycle_mode="sidestep_reentry",
        state="flat_waiting_reentry",
        started_at="2026-05-01T00:00:00+00:00",
        last_transition_at="2026-05-02T10:00:00+00:00",
        current_deal_id="deal-legacy-1",
        sidestep_count=1,
        tp_percent=5.0,
        principal_quote=101.5,
        reserved_quote=101.5,
        cumulative_realized_quote=0.0,
        cumulative_realized_percent=0.0,
        metadata_json="{}",
    )
    await model.OpenTrades.create(
        symbol="BTC/USDT",
        campaign_id="campaign-waiting-legacy",
        lifecycle_mode="classic_dca",
        exposure_state="long_exposed",
        current_price=95.0,
        reserved_reentry_quote=101.5,
        waiting_reference_price=101.5,
        waiting_reference_amount=1.0,
        waiting_reference_quote=101.5,
        virtual_waiting_profit=6.5,
        virtual_waiting_profit_percent=6.4,
        last_transition_at="2026-05-02T10:00:00+00:00",
    )

    trades = Trades()
    aggregated = await trades.get_trades_for_orders("BTC/USDT")

    assert aggregated is not None
    assert aggregated["campaign_id"] == "campaign-waiting-legacy"
    assert aggregated["lifecycle_mode"] == "sidestep_reentry"
    assert aggregated["exposure_state"] == "flat_waiting_reentry"
    assert aggregated["reserved_reentry_quote"] == 101.5
    assert aggregated["virtual_waiting_profit"] == 6.5
    assert aggregated["display_profit_percent"] == 6.4

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_closed_trades_hides_non_terminal_sidestep_legs(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.ClosedTrades.create(
        symbol="BTC/USDT",
        deal_id="11111111-1111-1111-1111-111111111111",
        close_date="2026-05-01 10:00:00",
        close_reason=TradeCloseReason.SIDESTEP_EXIT.value,
    )
    await model.ClosedTrades.create(
        symbol="SOL/USDT",
        deal_id="33333333-3333-3333-3333-333333333333",
        close_date="2026-05-01 10:30:00",
        close_reason=None,
    )
    await model.ClosedTrades.create(
        symbol="ETH/USDT",
        deal_id="22222222-2222-2222-2222-222222222222",
        close_date="2026-05-01 11:00:00",
        close_reason=TradeCloseReason.TAKE_PROFIT.value,
    )

    trades = Trades()
    closed_trades = await trades.get_closed_trades()
    closed_trades_length = await trades.get_closed_trades_length()

    assert [row["symbol"] for row in closed_trades] == ["ETH/USDT", "SOL/USDT"]
    assert closed_trades_length == 2

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_trade_executions_replays_full_sidestep_campaign_history(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    first_deal_id = "11111111-1111-1111-1111-111111111111"
    second_deal_id = "22222222-2222-2222-2222-222222222222"
    campaign_id = "campaign-replay-joined"

    await model.SpotCampaigns.create(
        campaign_id=campaign_id,
        symbol="BTC/USDT",
        lifecycle_mode="sidestep_reentry",
        state="completed_tp",
        started_at="2026-05-01T08:00:00+00:00",
        last_transition_at="2026-05-03T08:00:00+00:00",
        current_deal_id=None,
        sidestep_count=1,
        tp_percent=5.0,
        principal_quote=100.0,
        reserved_quote=0.0,
        cumulative_realized_quote=15.0,
        cumulative_realized_percent=15.0,
        metadata_json="{}",
    )
    await model.TradeExecutions.create(
        deal_id=first_deal_id,
        campaign_id=campaign_id,
        symbol="BTC/USDT",
        side="buy",
        role="base_order",
        timestamp="1000",
        price=100.0,
        amount=1.0,
        ordersize=100.0,
    )
    await model.TradeExecutions.create(
        deal_id=first_deal_id,
        campaign_id=campaign_id,
        symbol="BTC/USDT",
        side="sell",
        role="final_sell",
        timestamp="2000",
        price=108.0,
        amount=1.0,
        ordersize=108.0,
    )
    await model.TradeExecutions.create(
        deal_id=second_deal_id,
        campaign_id=campaign_id,
        symbol="BTC/USDT",
        side="buy",
        role="base_order",
        timestamp="3000",
        price=102.0,
        amount=1.0,
        ordersize=102.0,
    )
    await model.TradeExecutions.create(
        deal_id=second_deal_id,
        campaign_id=campaign_id,
        symbol="BTC/USDT",
        side="sell",
        role="final_sell",
        timestamp="4000",
        price=107.0,
        amount=1.0,
        ordersize=107.0,
    )

    trades = Trades()
    executions = await trades.get_trade_executions(second_deal_id)

    assert [row["deal_id"] for row in executions] == [
        first_deal_id,
        first_deal_id,
        second_deal_id,
        second_deal_id,
    ]
    assert [row["timestamp"] for row in executions] == ["1000", "2000", "3000", "4000"]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_open_trades_includes_campaign_metadata_for_sidestep_rows(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.SpotCampaigns.create(
        campaign_id="campaign-joined-1",
        symbol="BTC/USDT",
        lifecycle_mode="sidestep_reentry",
        state="active_long",
        started_at="2026-05-01T08:00:00+00:00",
        last_transition_at="2026-05-02T08:00:00+00:00",
        current_deal_id="deal-joined-1",
        sidestep_count=2,
        tp_percent=5.0,
        principal_quote=100.0,
        reserved_quote=0.0,
        cumulative_realized_quote=0.0,
        cumulative_realized_percent=0.0,
        metadata_json="{}",
    )
    await model.OpenTrades.create(
        symbol="BTC/USDT",
        deal_id="deal-joined-1",
        campaign_id="campaign-joined-1",
        lifecycle_mode="sidestep_reentry",
        exposure_state="long_exposed",
        open_date="2026-05-02T09:00:00+00:00",
    )
    await model.Trades.create(
        timestamp="1000",
        ordersize=100.0,
        fee=0.0,
        precision=3,
        amount=1.0,
        amount_fee=0.0,
        price=100.0,
        symbol="BTC/USDT",
        orderid="oid-joined-1",
        campaign_id="campaign-joined-1",
        bot="sidestep_BTC/USDT",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
    )

    trades = Trades()
    rows = await trades.get_open_trades()

    assert len(rows) == 1
    assert rows[0]["campaign_started_at"] == "2026-05-01T08:00:00+00:00"
    assert rows[0]["sidestep_count"] == 2
    assert rows[0]["campaign_realized_profit"] == 0.0
    assert rows[0]["campaign_total_profit"] == 0.0
    assert rows[0]["display_profit_percent"] == 0.0

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_open_trades_combines_campaign_realized_and_live_leg_profit(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.SpotCampaigns.create(
        campaign_id="campaign-live-1",
        symbol="ETH/USDT",
        lifecycle_mode="sidestep_reentry",
        state="active_long",
        started_at="2026-05-01T08:00:00+00:00",
        last_transition_at="2026-05-02T08:00:00+00:00",
        current_deal_id="deal-live-1",
        sidestep_count=1,
        tp_percent=5.0,
        principal_quote=100.0,
        reserved_quote=0.0,
        cumulative_realized_quote=7.0,
        cumulative_realized_percent=7.0,
        metadata_json="{}",
    )
    await model.OpenTrades.create(
        symbol="ETH/USDT",
        deal_id="deal-live-1",
        campaign_id="campaign-live-1",
        lifecycle_mode="sidestep_reentry",
        exposure_state="long_exposed",
        profit=3.0,
        profit_percent=2.5,
        cost=96.0,
        open_date="2026-05-02T09:00:00+00:00",
    )
    await model.Trades.create(
        timestamp="1000",
        ordersize=96.0,
        fee=0.0,
        precision=3,
        amount=1.0,
        amount_fee=0.0,
        price=96.0,
        symbol="ETH/USDT",
        orderid="oid-live-1",
        campaign_id="campaign-live-1",
        bot="sidestep_ETH/USDT",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
    )

    trades = Trades()
    rows = await trades.get_open_trades()

    assert len(rows) == 1
    assert rows[0]["campaign_realized_profit"] == 7.0
    assert rows[0]["campaign_total_profit"] == 10.0
    assert rows[0]["campaign_total_profit_percent"] == pytest.approx(10.0)
    assert rows[0]["display_profit"] == 10.0
    assert rows[0]["display_profit_percent"] == pytest.approx(10.0)

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_waiting_trades_combine_campaign_realized_and_virtual_profit(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.SpotCampaigns.create(
        campaign_id="campaign-waiting-1",
        symbol="SOL/USDT",
        lifecycle_mode="sidestep_reentry",
        state="flat_waiting_reentry",
        started_at="2026-05-01T08:00:00+00:00",
        last_transition_at="2026-05-02T10:00:00+00:00",
        current_deal_id="deal-waiting-1",
        sidestep_count=2,
        tp_percent=5.0,
        principal_quote=100.0,
        reserved_quote=96.0,
        cumulative_realized_quote=4.0,
        cumulative_realized_percent=4.0,
        metadata_json="{}",
    )
    await model.OpenTrades.create(
        symbol="SOL/USDT",
        deal_id="deal-waiting-1",
        campaign_id="campaign-waiting-1",
        lifecycle_mode="sidestep_reentry",
        exposure_state="flat_waiting_reentry",
        current_price=94.0,
        reserved_reentry_quote=96.0,
        waiting_reference_price=96.0,
        waiting_reference_amount=1.0,
        waiting_reference_quote=96.0,
        virtual_waiting_profit=6.0,
        virtual_waiting_profit_percent=6.25,
        open_date="2026-05-01T08:00:00+00:00",
        last_transition_at="2026-05-02T10:00:00+00:00",
    )

    trades = Trades()
    rows = await trades.get_waiting_trades()

    assert len(rows) == 1
    assert rows[0]["campaign_realized_profit"] == 4.0
    assert rows[0]["campaign_total_profit"] == 10.0
    assert rows[0]["campaign_total_profit_percent"] == pytest.approx(10.0)
    assert rows[0]["display_profit"] == 10.0
    assert rows[0]["display_profit_percent"] == pytest.approx(10.0)

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_open_trades_sorts_sidestep_rows_by_original_open_date(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.SpotCampaigns.create(
        campaign_id="campaign-late",
        symbol="LATE/USDT",
        lifecycle_mode="sidestep_reentry",
        state="active_long",
        started_at="2026-05-01T08:00:00+00:00",
        last_transition_at="2026-05-03T08:00:00+00:00",
        current_deal_id="deal-late",
        sidestep_count=1,
        tp_percent=5.0,
        principal_quote=100.0,
        reserved_quote=0.0,
        cumulative_realized_quote=0.0,
        cumulative_realized_percent=0.0,
        metadata_json="{}",
    )
    await model.OpenTrades.create(
        symbol="LATE/USDT",
        deal_id="deal-late",
        campaign_id="campaign-late",
        lifecycle_mode="sidestep_reentry",
        exposure_state="long_exposed",
        open_date="2026-05-03T09:00:00+00:00",
    )
    await model.Trades.create(
        timestamp="1777798800000",
        ordersize=100.0,
        fee=0.0,
        precision=3,
        amount=1.0,
        amount_fee=0.0,
        price=100.0,
        symbol="LATE/USDT",
        orderid="oid-late",
        campaign_id="campaign-late",
        bot="sidestep_LATE/USDT",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
    )

    await model.OpenTrades.create(
        symbol="EARLY/USDT",
        deal_id="deal-early",
        lifecycle_mode="classic_dca",
        exposure_state="long_exposed",
        open_date="2026-05-02T09:00:00+00:00",
    )
    await model.Trades.create(
        timestamp="1777712400000",
        ordersize=50.0,
        fee=0.0,
        precision=3,
        amount=1.0,
        amount_fee=0.0,
        price=50.0,
        symbol="EARLY/USDT",
        orderid="oid-early",
        bot="dca_EARLY/USDT",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
    )

    trades = Trades()
    rows = await trades.get_open_trades()

    assert [row["symbol"] for row in rows] == ["LATE/USDT", "EARLY/USDT"]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_waiting_trades_keep_campaign_start_order(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.SpotCampaigns.create(
        campaign_id="campaign-earlier",
        symbol="EARLIER/USDT",
        lifecycle_mode="sidestep_reentry",
        state="flat_waiting_reentry",
        started_at="2026-05-01T08:00:00+00:00",
        last_transition_at="2026-05-03T08:00:00+00:00",
        current_deal_id="deal-earlier",
        sidestep_count=1,
        tp_percent=5.0,
        principal_quote=100.0,
        reserved_quote=96.0,
        cumulative_realized_quote=0.0,
        cumulative_realized_percent=0.0,
        metadata_json="{}",
    )
    await model.OpenTrades.create(
        symbol="EARLIER/USDT",
        deal_id="deal-earlier",
        campaign_id="campaign-earlier",
        lifecycle_mode="sidestep_reentry",
        exposure_state="flat_waiting_reentry",
        open_date="2026-05-03T09:00:00+00:00",
        last_transition_at="2026-05-03T08:00:00+00:00",
        waiting_reference_quote=96.0,
    )

    await model.SpotCampaigns.create(
        campaign_id="campaign-later",
        symbol="LATER/USDT",
        lifecycle_mode="sidestep_reentry",
        state="flat_waiting_reentry",
        started_at="2026-05-02T08:00:00+00:00",
        last_transition_at="2026-05-02T08:00:00+00:00",
        current_deal_id="deal-later",
        sidestep_count=1,
        tp_percent=5.0,
        principal_quote=100.0,
        reserved_quote=96.0,
        cumulative_realized_quote=0.0,
        cumulative_realized_percent=0.0,
        metadata_json="{}",
    )
    await model.OpenTrades.create(
        symbol="LATER/USDT",
        deal_id="deal-later",
        campaign_id="campaign-later",
        lifecycle_mode="sidestep_reentry",
        exposure_state="flat_waiting_reentry",
        open_date="2026-05-02T09:00:00+00:00",
        last_transition_at="2026-05-02T08:00:00+00:00",
        waiting_reference_quote=96.0,
    )

    trades = Trades()
    rows = await trades.get_waiting_trades()

    assert [row["symbol"] for row in rows] == ["EARLIER/USDT", "LATER/USDT"]

    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_open_trades_repairs_legacy_classic_open_date_from_baseorder(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.OpenTrades.create(
        symbol="LEGACY/USDT",
        deal_id="deal-legacy",
        lifecycle_mode="classic_dca",
        exposure_state="long_exposed",
        open_date="1700000000000.0",
    )
    await model.Trades.create(
        timestamp="1700000000000",
        ordersize=50.0,
        fee=0.0,
        precision=3,
        amount=1.0,
        amount_fee=0.0,
        price=50.0,
        symbol="LEGACY/USDT",
        orderid="oid-legacy",
        bot="dca_LEGACY/USDT",
        ordertype="market",
        baseorder=True,
        safetyorder=False,
        order_count=0,
        so_percentage=None,
        direction="long",
        side="buy",
    )

    trades = Trades()
    rows = await trades.get_open_trades()

    assert len(rows) == 1
    assert rows[0]["open_date"] == "2023-11-14 22:13:20+00:00"

    await Tortoise.close_connections()
