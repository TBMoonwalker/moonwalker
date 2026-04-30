import pytest
from service.dca import Dca
from service.spot_sidestep_campaign import SpotSidestepCampaignService


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
