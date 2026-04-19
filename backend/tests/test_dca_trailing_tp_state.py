import pytest
from service.autopilot import ResolvedTradingPolicy
from service.dca import Dca


def _build_trades() -> dict[str, object]:
    return {
        "symbol": "XPL/USDC",
        "bot": "symsignal_XPLUSDC",
        "direction": "long",
        "total_cost": 100.0,
        "total_amount": 1.0,
        "fee": 0.0,
        "timestamp": 1_742_000_000_000,
        "safetyorders_count": 0,
        "safetyorders": [],
        "bo_price": 100.0,
    }


def _configure_dca(dca: Dca) -> None:
    dca.config = {
        "trailing_tp": 1.0,
        "mstc": 0,
        "tp_spike_confirm_enabled": False,
    }


def _build_policy() -> ResolvedTradingPolicy:
    return ResolvedTradingPolicy(
        symbol="XPL/USDC",
        mode="low",
        effective_max_bots=2,
        take_profit=10.0,
        baseline_take_profit=10.0,
        stop_loss=5.0,
        stop_loss_timeout=0,
        green_phase_active=False,
        green_phase_extra_deals=0,
        adaptive_tp_applied=False,
        adaptive_reason_code=None,
        adaptive_trust_direction=None,
        adaptive_trust_score=None,
        adaptive_entry_size_applied=False,
        adaptive_entry_reason_code=None,
        memory_status="fresh",
        baseline_base_order=50.0,
        entry_order_size=50.0,
        suggested_base_order=50.0,
    )


@pytest.mark.asyncio
async def test_trailing_tp_state_is_instance_local(monkeypatch) -> None:
    first = Dca()
    second = Dca()
    _configure_dca(first)
    _configure_dca(second)

    first_sell_calls: list[dict[str, object]] = []
    second_sell_calls: list[dict[str, object]] = []

    async def fake_first_sell_order(order, _config) -> None:
        first_sell_calls.append(order)

    async def fake_second_sell_order(order, _config) -> None:
        second_sell_calls.append(order)

    async def fake_update_statistic_data(_payload) -> None:
        return None

    monkeypatch.setattr(first.orders, "receive_sell_order", fake_first_sell_order)
    monkeypatch.setattr(second.orders, "receive_sell_order", fake_second_sell_order)
    monkeypatch.setattr(
        first.statistic, "update_statistic_data", fake_update_statistic_data
    )
    monkeypatch.setattr(
        second.statistic, "update_statistic_data", fake_update_statistic_data
    )

    trades = _build_trades()

    await first._Dca__calculate_tp(112.0, trades, _build_policy())
    await second._Dca__calculate_tp(110.8, trades, _build_policy())

    assert first_sell_calls == []
    assert second_sell_calls == []
    assert first._trailing_tp_peaks["XPL/USDC"] == pytest.approx(12.0)
    assert second._trailing_tp_peaks["XPL/USDC"] == pytest.approx(10.8)
