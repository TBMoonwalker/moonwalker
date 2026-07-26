"""Runtime integration tests for recovery-target dynamic DCA."""

import json

import pytest
from service.dca import Dca
from service.dca_recovery_sizing import RecoverySizingPolicy


def _policy_json() -> str:
    return json.dumps(
        RecoverySizingPolicy.from_dict(
            {
                "mode": "recovery_target",
                "atr_timeframe": "4h",
                "atr_length": 14,
                "spacing_atr_multiplier": 3.0,
                "minimum_spacing_percent": 5.0,
                "spacing_step_scale": 1.6,
                "recovery_atr_multiplier": 5.5,
                "minimum_recovery_percent": 12.0,
                "maximum_recovery_percent": 30.0,
                "maximum_deal_quote": 250.0,
                "minimum_tp_improvement_percent": 5.0,
            }
        ).to_dict()
    )


def _config() -> dict:
    return {
        "trade_mode": "dynamic_dca",
        "dca_strategy": "ema_swing",
        "timeframe": "4h",
        "tp": 1.0,
        "os": 1.0,
        "ss": 1.6,
        "mstc": 5,
        "sos": 5.0,
        "so": 12.0,
        "bo": 12.0,
        "trade_safety_order_budget_ratio": 0.95,
    }


@pytest.mark.asyncio
async def test_recovery_mode_rejects_0g_candidate_inside_atr_spacing(
    monkeypatch,
) -> None:
    dca = Dca()
    dca.config = _config()
    buys: list[dict] = []
    updates: list[dict] = []
    strategy_calls = 0

    async def fake_atr(*_args, **_kwargs):
        return 1.0, {"regime": "mid", "atr_percent": 1.789269}

    async def fake_strategy(_symbol):
        nonlocal strategy_calls
        strategy_calls += 1
        return True, True

    async def fake_update(payload, _symbol):
        updates.append(payload)
        return None

    async def fake_buy(order, _config_snapshot):
        buys.append(order)
        return True

    async def fake_stat(_payload):
        return None

    monkeypatch.setattr(
        dca.indicators,
        "calculate_atr_regime_multiplier",
        fake_atr,
    )
    monkeypatch.setattr(dca, "_Dca__dynamic_dca_strategy", fake_strategy)
    monkeypatch.setattr(dca.trades, "update_open_trades", fake_update)
    monkeypatch.setattr(dca.orders, "receive_buy_order", fake_buy)
    monkeypatch.setattr(dca.statistic, "update_statistic_data", fake_stat)

    await dca._Dca__calculate_dca(
        0.556,
        {
            "symbol": "0G/USDC",
            "direction": "long",
            "bot": "symsignal_0GUSDC",
            "ordertype": "market",
            "bo_price": 0.568,
            "fee": 0.0,
            "total_cost": 11.99048,
            "total_amount": 21.0899455,
            "safetyorders_count": 0,
            "safetyorders": [],
            "dca_sizing_mode": "recovery_target",
            "dca_policy_json": _policy_json(),
            "dca_reference_price": 0.568,
            "dca_reference_atr_percent": 1.789269,
            "dca_next_trigger_price": 0.0,
        },
    )

    assert strategy_calls == 0
    assert buys == []
    decision = json.loads(updates[-1]["dca_last_decision_json"])
    assert decision["reason"] == "waiting_for_atr_spacing"


@pytest.mark.asyncio
async def test_recovery_mode_surfaces_missing_deal_budget_before_signal(
    monkeypatch,
) -> None:
    dca = Dca()
    dca.config = _config()
    updates: list[dict] = []
    strategy_calls = 0

    async def fake_atr(*_args, **_kwargs):
        return 1.0, {"regime": "mid", "atr_percent": 3.0}

    async def fake_strategy(_symbol):
        nonlocal strategy_calls
        strategy_calls += 1
        return True, True

    async def fake_update(payload, _symbol):
        updates.append(payload)
        return None

    monkeypatch.setattr(
        dca.indicators,
        "calculate_atr_regime_multiplier",
        fake_atr,
    )
    monkeypatch.setattr(dca, "_Dca__dynamic_dca_strategy", fake_strategy)
    monkeypatch.setattr(dca.trades, "update_open_trades", fake_update)

    invalid_policy = json.loads(_policy_json())
    invalid_policy["maximum_deal_quote"] = 0
    matched, _pnl, details = await dca._Dca__evaluate_recovery_dca_trigger(
        {
            "symbol": "0G/USDC",
            "bo_price": 0.568,
            "safetyorders_count": 0,
            "safetyorders": [],
            "dca_reference_price": 0.568,
            "dca_reference_atr_percent": 3.0,
            "dca_next_trigger_price": 0.0,
        },
        0.5,
        -12.0,
        RecoverySizingPolicy.from_dict(invalid_policy),
    )

    assert matched is False
    assert strategy_calls == 0
    assert details["reason"] == "missing_deal_budget"
    decision = json.loads(updates[-1]["dca_last_decision_json"])
    assert decision["reason"] == "missing_deal_budget"


@pytest.mark.asyncio
async def test_recovery_mode_places_target_sized_0g_order(monkeypatch) -> None:
    dca = Dca()
    dca.config = _config()
    buys: list[dict] = []

    async def fake_atr(*_args, **_kwargs):
        return 1.5, {"regime": "high", "atr_percent": 3.1376532711}

    async def fake_strategy(_symbol):
        return True, True

    async def fake_update(_payload, _symbol):
        return None

    async def fake_balance(*_args, **_kwargs):
        return 1000.0

    async def fake_minimum(*_args, **_kwargs):
        return 5.0

    async def fake_buy(order, _config_snapshot):
        buys.append(order)
        return True

    async def fake_stat(_payload):
        return None

    monkeypatch.setattr(
        dca.indicators,
        "calculate_atr_regime_multiplier",
        fake_atr,
    )
    monkeypatch.setattr(dca, "_Dca__dynamic_dca_strategy", fake_strategy)
    monkeypatch.setattr(dca.trades, "update_open_trades", fake_update)
    monkeypatch.setattr(dca.exchange, "get_free_quote_balance", fake_balance)
    monkeypatch.setattr(dca.exchange, "get_minimum_buy_notional", fake_minimum)
    monkeypatch.setattr(dca.orders, "receive_buy_order", fake_buy)
    monkeypatch.setattr(dca.statistic, "update_statistic_data", fake_stat)

    first_cost = 3.8010819527
    await dca._Dca__calculate_dca(
        0.306,
        {
            "symbol": "0G/USDC",
            "direction": "long",
            "bot": "symsignal_0GUSDC",
            "ordertype": "market",
            "bo_price": 0.568,
            "fee": 0.0,
            "total_cost": 11.99048 + first_cost,
            "total_amount": 21.0899455 + (first_cost / 0.495),
            "safetyorders_count": 1,
            "safetyorders": [
                {
                    "price": 0.495,
                    "so_percentage": -12.9,
                    "ordersize": first_cost,
                }
            ],
            "dca_sizing_mode": "recovery_target",
            "dca_policy_json": _policy_json(),
            "dca_reference_price": 0.495,
            "dca_reference_atr_percent": 1.5880084343,
            "dca_next_trigger_price": 0.0,
        },
    )

    assert len(buys) == 1
    assert buys[0]["ordersize"] == pytest.approx(34.61260727)
    assert buys[0]["strategy_name"] == "ema_swing"
    assert buys[0]["maximum_buy_price"] == pytest.approx(0.457677)
    metadata = json.loads(buys[0]["metadata_json"])
    assert metadata["recovery_so"]["target_recovery_percent"] == pytest.approx(
        17.25709299
    )
    assert metadata["recovery_so"]["projected_tp_price"] == pytest.approx(0.35880670)
    assert metadata["recovery_so"]["execution_guard_enabled"] is True
    assert metadata["recovery_so"]["execution_drift_percent"] == pytest.approx(0.5)
