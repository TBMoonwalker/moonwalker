"""Engine-side exit price guard (G1) behavior for market sells."""

import ccxt.async_support as ccxt
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
        "sellable_amount": 1.0,
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
        "tp_spike_confirm_enabled": False,
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


def _patch_engine(
    dca: Dca,
    monkeypatch,
    *,
    bid_price: str | None = "111.0",
    fetch_error: Exception | None = None,
    fetch_calls: list[str] | None = None,
    stat_payloads: list[dict[str, object]] | None = None,
) -> None:
    """Patch statistic writes and the exit price guard fetch on a Dca engine."""

    async def fake_update_statistic_data(payload) -> None:
        if stat_payloads is not None:
            stat_payloads.append(payload)

    async def fake_get_bid_price_for_symbol(symbol: str) -> str:
        if fetch_error is not None:
            raise fetch_error
        if fetch_calls is not None:
            fetch_calls.append(symbol)
        if bid_price is None:
            return ""
        return bid_price

    monkeypatch.setattr(
        dca.statistic, "update_statistic_data", fake_update_statistic_data
    )
    monkeypatch.setattr(
        dca.exchange, "get_bid_price_for_symbol", fake_get_bid_price_for_symbol
    )


@pytest.mark.asyncio
async def test_market_tp_sell_proceeds_with_verified_price(monkeypatch) -> None:
    dca = Dca()
    _configure_dca(dca)
    sell_calls: list[dict[str, object]] = []

    async def fake_receive_sell_order(order, _config) -> None:
        sell_calls.append(order)

    monkeypatch.setattr(
        dca.order_lifecycle, "receive_sell_order", fake_receive_sell_order
    )
    _patch_engine(dca, monkeypatch, bid_price="111.0")

    await dca._Dca__calculate_tp(110.5, _build_trades(), _build_policy())

    assert len(sell_calls) == 1
    assert sell_calls[0]["current_price"] == pytest.approx(111.0)
    assert sell_calls[0]["sell_reason"] == "take_profit"
    assert sell_calls[0]["exit_guard_min_price"] == pytest.approx(110.0)
    assert sell_calls[0]["exit_guard_max_price"] is None
    assert sell_calls[0]["fallback_min_price"] == pytest.approx(110.0)


@pytest.mark.asyncio
async def test_market_tp_sell_aborts_when_fresh_price_below_tp(
    monkeypatch,
) -> None:
    dca = Dca()
    _configure_dca(dca)
    sell_calls: list[dict[str, object]] = []
    stat_payloads: list[dict[str, object]] = []

    async def fake_receive_sell_order(_order, _config) -> None:
        sell_calls.append(_order)

    monkeypatch.setattr(
        dca.order_lifecycle, "receive_sell_order", fake_receive_sell_order
    )
    _patch_engine(dca, monkeypatch, bid_price="109.5", stat_payloads=stat_payloads)

    await dca._Dca__calculate_tp(111.0, _build_trades(), _build_policy())

    assert sell_calls == []
    assert stat_payloads[-1]["sell"] is False
    assert stat_payloads[-1]["current_price"] == pytest.approx(109.5)


@pytest.mark.asyncio
async def test_market_stop_loss_proceeds_when_fresh_price_within_bound(
    monkeypatch,
) -> None:
    dca = Dca()
    _configure_dca(dca)
    sell_calls: list[dict[str, object]] = []

    async def fake_receive_sell_order(order, _config) -> None:
        sell_calls.append(order)

    monkeypatch.setattr(
        dca.order_lifecycle, "receive_sell_order", fake_receive_sell_order
    )
    _patch_engine(dca, monkeypatch, bid_price="94.0")

    await dca._Dca__calculate_tp(94.0, _build_trades(), _build_policy())

    assert len(sell_calls) == 1
    assert sell_calls[0]["sell_reason"] == "stop_loss"
    assert sell_calls[0]["exit_guard_max_price"] == pytest.approx(95.0)
    assert sell_calls[0]["exit_guard_min_price"] is None


@pytest.mark.asyncio
async def test_market_stop_loss_aborts_when_fresh_price_recovered(
    monkeypatch,
) -> None:
    dca = Dca()
    _configure_dca(dca)
    sell_calls: list[dict[str, object]] = []
    stat_payloads: list[dict[str, object]] = []

    async def fake_receive_sell_order(_order, _config) -> None:
        sell_calls.append(_order)

    monkeypatch.setattr(
        dca.order_lifecycle, "receive_sell_order", fake_receive_sell_order
    )
    _patch_engine(dca, monkeypatch, bid_price="96.0", stat_payloads=stat_payloads)

    await dca._Dca__calculate_tp(94.0, _build_trades(), _build_policy())

    assert sell_calls == []
    assert stat_payloads[-1]["sell"] is False
    assert stat_payloads[-1]["current_price"] == pytest.approx(96.0)


@pytest.mark.asyncio
async def test_market_trailing_exit_uses_pnl_inverted_bound(monkeypatch) -> None:
    dca = Dca()
    _configure_dca(dca, trailing_tp=1.0)
    sell_calls: list[dict[str, object]] = []

    async def fake_receive_sell_order(order, _config) -> None:
        sell_calls.append(order)

    monkeypatch.setattr(
        dca.order_lifecycle, "receive_sell_order", fake_receive_sell_order
    )
    _patch_engine(dca, monkeypatch, bid_price="109.5")

    trades = _build_trades()
    await dca._Dca__calculate_tp(112.0, trades, _build_policy())
    assert sell_calls == []
    await dca._Dca__calculate_tp(108.5, trades, _build_policy())

    assert len(sell_calls) == 1
    assert sell_calls[0]["sell_reason"] == "trailing_take_profit"
    assert sell_calls[0]["exit_guard_min_price"] == pytest.approx(109.0)
    assert sell_calls[0]["current_price"] == pytest.approx(109.5)


@pytest.mark.asyncio
async def test_market_trailing_exit_aborts_when_fresh_price_drops_out(
    monkeypatch,
) -> None:
    dca = Dca()
    _configure_dca(dca, trailing_tp=1.0)
    sell_calls: list[dict[str, object]] = []

    async def fake_receive_sell_order(_order, _config) -> None:
        sell_calls.append(_order)

    monkeypatch.setattr(
        dca.order_lifecycle, "receive_sell_order", fake_receive_sell_order
    )
    _patch_engine(dca, monkeypatch, bid_price="108.0")

    trades = _build_trades()
    await dca._Dca__calculate_tp(112.0, trades, _build_policy())
    await dca._Dca__calculate_tp(108.5, trades, _build_policy())

    assert sell_calls == []


@pytest.mark.asyncio
async def test_market_autopilot_timeout_exit_uses_sl_inverted_bound(
    monkeypatch,
) -> None:
    dca = Dca()
    _configure_dca(dca)
    sell_calls: list[dict[str, object]] = []

    async def fake_receive_sell_order(order, _config) -> None:
        sell_calls.append(order)

    monkeypatch.setattr(
        dca.order_lifecycle, "receive_sell_order", fake_receive_sell_order
    )
    _patch_engine(dca, monkeypatch, bid_price="95.5")

    policy = _build_policy(stop_loss_timeout=1)
    await dca._Dca__calculate_tp(97.0, _build_trades(), policy)

    assert len(sell_calls) == 1
    assert sell_calls[0]["sell_reason"] == "autopilot_timeout"
    assert sell_calls[0]["exit_guard_min_price"] == pytest.approx(95.0)
    assert sell_calls[0]["exit_guard_max_price"] is None


@pytest.mark.asyncio
async def test_market_autopilot_timeout_exit_aborts_when_fresh_price_falls_out(
    monkeypatch,
) -> None:
    dca = Dca()
    _configure_dca(dca)
    sell_calls: list[dict[str, object]] = []

    async def fake_receive_sell_order(_order, _config) -> None:
        sell_calls.append(_order)

    monkeypatch.setattr(
        dca.order_lifecycle, "receive_sell_order", fake_receive_sell_order
    )
    _patch_engine(dca, monkeypatch, bid_price="94.0")

    policy = _build_policy(stop_loss_timeout=1)
    await dca._Dca__calculate_tp(97.0, _build_trades(), policy)

    assert sell_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fetch_error",
    [RuntimeError("ticker unavailable"), ccxt.NetworkError("network down")],
)
async def test_market_sell_aborts_when_price_fetch_fails(
    monkeypatch,
    fetch_error: Exception,
) -> None:
    dca = Dca()
    _configure_dca(dca)
    sell_calls: list[dict[str, object]] = []

    async def fake_receive_sell_order(_order, _config) -> None:
        sell_calls.append(_order)

    monkeypatch.setattr(
        dca.order_lifecycle, "receive_sell_order", fake_receive_sell_order
    )
    _patch_engine(dca, monkeypatch, fetch_error=fetch_error)

    await dca._Dca__calculate_tp(111.0, _build_trades(), _build_policy())

    assert sell_calls == []


@pytest.mark.asyncio
async def test_market_sell_aborts_when_price_fetch_returns_empty(monkeypatch) -> None:
    dca = Dca()
    _configure_dca(dca)
    sell_calls: list[dict[str, object]] = []

    async def fake_receive_sell_order(_order, _config) -> None:
        sell_calls.append(_order)

    monkeypatch.setattr(
        dca.order_lifecycle, "receive_sell_order", fake_receive_sell_order
    )
    _patch_engine(dca, monkeypatch, bid_price=None)

    await dca._Dca__calculate_tp(111.0, _build_trades(), _build_policy())

    assert sell_calls == []


@pytest.mark.asyncio
async def test_limit_sell_mode_skips_exit_price_fetch(monkeypatch) -> None:
    dca = Dca()
    _configure_dca(dca, sell_order_type="limit")
    sell_calls: list[dict[str, object]] = []
    fetch_calls: list[str] = []

    async def fake_receive_sell_order(order, _config) -> None:
        sell_calls.append(order)

    monkeypatch.setattr(
        dca.order_lifecycle, "receive_sell_order", fake_receive_sell_order
    )
    _patch_engine(dca, monkeypatch, bid_price="111.0", fetch_calls=fetch_calls)

    await dca._Dca__calculate_tp(111.0, _build_trades(), _build_policy())

    assert fetch_calls == []
    assert len(sell_calls) == 1
    assert sell_calls[0]["current_price"] == pytest.approx(111.0)
    assert sell_calls[0]["limit_price"] == pytest.approx(110.0)
    assert sell_calls[0]["exit_guard_min_price"] == pytest.approx(110.0)
