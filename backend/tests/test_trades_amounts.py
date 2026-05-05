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
async def test_get_open_trades_sorts_by_campaign_or_trade_entry_time(
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
        started_at="2026-05-03T08:00:00+00:00",
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
        timestamp="3000",
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
        open_date="2026-05-01T09:00:00+00:00",
    )
    await model.Trades.create(
        timestamp="1000",
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

    assert [row["symbol"] for row in rows] == ["EARLY/USDT", "LATE/USDT"]

    await Tortoise.close_connections()
