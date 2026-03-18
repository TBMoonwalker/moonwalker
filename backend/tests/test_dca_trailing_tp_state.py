import pytest
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
    dca.tp = 10.0
    dca.sl = 5.0
    dca.sl_timeout = 0


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

    await first._Dca__calculate_tp(112.0, trades)
    await second._Dca__calculate_tp(110.8, trades)

    assert first_sell_calls == []
    assert second_sell_calls == []
    assert first._trailing_tp_peaks["XPL/USDC"] == pytest.approx(12.0)
    assert second._trailing_tp_peaks["XPL/USDC"] == pytest.approx(10.8)
