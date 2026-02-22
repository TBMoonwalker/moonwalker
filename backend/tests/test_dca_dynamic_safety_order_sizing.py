import pytest
from service.dca import Dca


@pytest.mark.asyncio
async def test_dynamic_dca_sizing_uses_base_order_and_factors(monkeypatch):
    dca = Dca()
    dca.config = {
        "bo": 100.0,
        "trade_safety_order_budget_ratio": 0.95,
        "dynamic_so_ath_cache_ttl": 60,
    }

    async def fake_ath(*_args, **_kwargs):
        return 110.0, "1m"

    async def fake_atr(*_args, **_kwargs):
        return 1.5, {"regime": "high", "atr_percent": 2.1}

    async def fake_quote_balance(*_args, **_kwargs):
        return 1000.0

    monkeypatch.setattr(dca.ath_service, "get_recent_ath", fake_ath)
    monkeypatch.setattr(
        dca.indicators,
        "calculate_atr_regime_multiplier",
        fake_atr,
    )
    monkeypatch.setattr(dca.exchange, "get_free_quote_balance", fake_quote_balance)

    final_size, details = await dca._Dca__resolve_safety_order_size(
        trades={"symbol": "BTC/USDT", "safetyorders": []},
        current_price=100.0,
        actual_pnl=-10.0,
        volume_scale=1.0,
        so_index=2,
        threshold_percentage=-5.0,
        dynamic_dca=True,
    )

    assert final_size == pytest.approx(478.63636, rel=1e-6)
    assert details.get("skip") != "true"
    assert details["base_cost"] == 100.0
    assert details["budget_ratio"] == 0.95


@pytest.mark.asyncio
async def test_dynamic_dca_sizing_caps_by_budget_and_skips_below_base_order(
    monkeypatch,
):
    dca = Dca()
    dca.config = {
        "bo": 100.0,
        "trade_safety_order_budget_ratio": 0.5,
        "dynamic_so_ath_cache_ttl": 60,
    }

    async def fake_ath(*_args, **_kwargs):
        return 120.0, "1m"

    async def fake_atr(*_args, **_kwargs):
        return 1.5, {"regime": "high", "atr_percent": 2.5}

    async def fake_quote_balance(*_args, **_kwargs):
        return 100.0

    monkeypatch.setattr(dca.ath_service, "get_recent_ath", fake_ath)
    monkeypatch.setattr(
        dca.indicators,
        "calculate_atr_regime_multiplier",
        fake_atr,
    )
    monkeypatch.setattr(dca.exchange, "get_free_quote_balance", fake_quote_balance)

    final_size, details = await dca._Dca__resolve_safety_order_size(
        trades={"symbol": "BTC/USDT", "safetyorders": []},
        current_price=100.0,
        actual_pnl=-20.0,
        volume_scale=1.0,
        so_index=1,
        threshold_percentage=-10.0,
        dynamic_dca=True,
    )

    assert final_size == 50.0
    assert details["skip"] == "true"
    assert "below base order amount" in str(details["error"])


@pytest.mark.asyncio
async def test_dynamic_dca_sizing_uses_budget_ratio_default(monkeypatch):
    dca = Dca()
    dca.config = {
        "bo": 100.0,
        "dynamic_so_ath_cache_ttl": 60,
    }

    async def fake_ath(*_args, **_kwargs):
        return 100.0, "1m"

    async def fake_atr(*_args, **_kwargs):
        return 1.0, {"regime": "mid", "atr_percent": 1.0}

    async def fake_quote_balance(*_args, **_kwargs):
        return 1000.0

    monkeypatch.setattr(dca.ath_service, "get_recent_ath", fake_ath)
    monkeypatch.setattr(
        dca.indicators,
        "calculate_atr_regime_multiplier",
        fake_atr,
    )
    monkeypatch.setattr(dca.exchange, "get_free_quote_balance", fake_quote_balance)

    _, details = await dca._Dca__resolve_safety_order_size(
        trades={"symbol": "BTC/USDT", "safetyorders": []},
        current_price=100.0,
        actual_pnl=-1.0,
        volume_scale=1.0,
        so_index=1,
        threshold_percentage=-1.0,
        dynamic_dca=True,
    )

    assert details["budget_ratio"] == 0.95
