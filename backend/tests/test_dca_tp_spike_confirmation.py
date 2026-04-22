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


def _configure_dca(dca: Dca, **config_overrides: object) -> None:
    dca.config = {
        "trailing_tp": 0,
        "mstc": 0,
        "tp_spike_confirm_enabled": True,
        "tp_spike_confirm_seconds": 3,
        "tp_spike_confirm_ticks": 0,
        **config_overrides,
    }


def _build_policy(**overrides: object) -> ResolvedTradingPolicy:
    payload = {
        "symbol": "XPL/USDC",
        "mode": "low",
        "effective_max_bots": 2,
        "take_profit": 10.0,
        "baseline_take_profit": 10.0,
        "stop_loss": 5.0,
        "stop_loss_timeout": 0,
        "green_phase_active": False,
        "green_phase_extra_deals": 0,
        "adaptive_tp_applied": False,
        "adaptive_reason_code": None,
        "adaptive_trust_direction": None,
        "adaptive_trust_score": None,
        "adaptive_entry_size_applied": False,
        "adaptive_entry_reason_code": None,
        "memory_status": "fresh",
        "baseline_base_order": 50.0,
        "entry_order_size": 50.0,
        "suggested_base_order": 50.0,
    }
    payload.update(overrides)
    return ResolvedTradingPolicy(**payload)


@pytest.mark.asyncio
async def test_tp_spike_confirmation_skips_single_tick_wick(monkeypatch) -> None:
    dca = Dca()
    _configure_dca(dca)
    sell_calls: list[dict[str, object]] = []

    async def fake_receive_sell_order(order, _config) -> None:
        sell_calls.append(order)

    async def fake_update_statistic_data(_payload) -> None:
        return None

    monkeypatch.setattr(dca.orders, "receive_sell_order", fake_receive_sell_order)
    monkeypatch.setattr(
        dca.statistic, "update_statistic_data", fake_update_statistic_data
    )
    monkeypatch.setattr(dca, "_Dca__get_monotonic_time", lambda: 100.0)

    await dca._Dca__calculate_tp(111.0, _build_trades(), _build_policy())

    assert sell_calls == []
    assert "XPL/USDC" in dca._pending_tp_confirmations


@pytest.mark.asyncio
async def test_tp_spike_confirmation_sells_after_duration_and_tick_filter(
    monkeypatch,
) -> None:
    dca = Dca()
    _configure_dca(dca, tp_spike_confirm_ticks=2)
    sell_calls: list[dict[str, object]] = []
    clock = {"now": 100.0}

    async def fake_receive_sell_order(order, _config) -> None:
        sell_calls.append(order)

    async def fake_update_statistic_data(_payload) -> None:
        return None

    monkeypatch.setattr(dca.orders, "receive_sell_order", fake_receive_sell_order)
    monkeypatch.setattr(
        dca.statistic, "update_statistic_data", fake_update_statistic_data
    )
    monkeypatch.setattr(dca, "_Dca__get_monotonic_time", lambda: clock["now"])

    trades = _build_trades()
    await dca._Dca__calculate_tp(111.0, trades, _build_policy())
    clock["now"] = 103.2
    await dca._Dca__calculate_tp(111.4, trades, _build_policy())

    assert len(sell_calls) == 1
    assert sell_calls[0]["symbol"] == "XPL/USDC"
    assert sell_calls[0]["fallback_min_price"] == pytest.approx(110.0)
    assert "XPL/USDC" not in dca._pending_tp_confirmations


@pytest.mark.asyncio
async def test_tp_spike_confirmation_restarts_after_fade_below_tp(monkeypatch) -> None:
    dca = Dca()
    _configure_dca(dca)
    sell_calls: list[dict[str, object]] = []
    clock = {"now": 100.0}

    async def fake_receive_sell_order(order, _config) -> None:
        sell_calls.append(order)

    async def fake_update_statistic_data(_payload) -> None:
        return None

    monkeypatch.setattr(dca.orders, "receive_sell_order", fake_receive_sell_order)
    monkeypatch.setattr(
        dca.statistic, "update_statistic_data", fake_update_statistic_data
    )
    monkeypatch.setattr(dca, "_Dca__get_monotonic_time", lambda: clock["now"])

    trades = _build_trades()
    await dca._Dca__calculate_tp(111.0, trades, _build_policy())
    clock["now"] = 101.0
    await dca._Dca__calculate_tp(109.0, trades, _build_policy())
    clock["now"] = 103.5
    await dca._Dca__calculate_tp(111.2, trades, _build_policy())
    clock["now"] = 106.7
    await dca._Dca__calculate_tp(111.3, trades, _build_policy())

    assert len(sell_calls) == 1
    assert sell_calls[0]["fallback_min_price"] == pytest.approx(110.0)


@pytest.mark.asyncio
async def test_tp_spike_confirmation_does_not_delay_stop_loss(monkeypatch) -> None:
    dca = Dca()
    _configure_dca(dca)
    sell_calls: list[dict[str, object]] = []

    async def fake_receive_sell_order(order, _config) -> None:
        sell_calls.append(order)

    async def fake_update_statistic_data(_payload) -> None:
        return None

    monkeypatch.setattr(dca.orders, "receive_sell_order", fake_receive_sell_order)
    monkeypatch.setattr(
        dca.statistic, "update_statistic_data", fake_update_statistic_data
    )
    monkeypatch.setattr(dca, "_Dca__get_monotonic_time", lambda: 100.0)

    trades = _build_trades()
    trades["safetyorders_count"] = 0
    await dca._Dca__calculate_tp(94.0, trades, _build_policy())

    assert len(sell_calls) == 1
    assert sell_calls[0]["symbol"] == "XPL/USDC"
