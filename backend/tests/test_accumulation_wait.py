"""Numeric wait levels follow the same gate order as live strategy decisions."""

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from service.accumulation_strategy import (
    AccumulationGuard,
    AccumulationMarket,
    AccumulationObservations,
    AccumulationParameters,
    accumulation_signal_reason,
)
from service.accumulation_wait import accumulation_wait_condition

PARAMETERS = AccumulationParameters()
HOUR = 3_600_000


@pytest.mark.parametrize(
    ("close", "previous", "reason", "target", "direction"),
    [
        ("111", "110", "WAIT_DECLINE", "110", "below"),
        ("109", "110", "WAIT_DEPTH", "107.0", "at_or_below"),
    ],
)
def test_entry_level_uses_actual_peak_atr_and_decline_gate(
    close, previous, reason, target, direction
):
    market = AccumulationMarket(
        HOUR, close, previous, "110", "2", str((110 - Decimal(close)) / 2)
    )
    state = AccumulationObservations(HOUR, 0)
    assert accumulation_signal_reason(market, state, None, PARAMETERS) == reason
    wait = accumulation_wait_condition(market, state, None, PARAMETERS, reason)
    assert wait["levels"][0]["target_price"] == target
    assert wait["levels"][0]["direction"] == direction
    expected = (Decimal(target) / Decimal(close) - 1) * 100
    assert abs(Decimal(wait["levels"][0]["change_percent"]) - expected) < Decimal(
        "1e-25"
    )
    assert wait["next_close_ms"] == 2 * HOUR


def test_rearm_explains_alternatives_without_promising_buy_at_recovery():
    market = AccumulationMarket(2 * HOUR, "99", "100", "110", "2", "5.5")
    state = AccumulationObservations(2 * HOUR, 1)
    guard = AccumulationGuard(str(uuid4()), HOUR, "100", "2", 1, 1)
    assert accumulation_signal_reason(market, state, guard, PARAMETERS) == "WAIT_REARM"
    wait = accumulation_wait_condition(market, state, guard, PARAMETERS, "WAIT_REARM")
    assert [(level["kind"], level["target_price"]) for level in wait["levels"]] == [
        ("further_decline", "98"),
        ("recovery_then_correction", "102"),
    ]
    recovered = replace(state, recovery_ready=True, high_close="105", atr_at_high="1")
    market = replace(market, close="104.5", previous_close="105")
    wait = accumulation_wait_condition(
        market, recovered, guard, PARAMETERS, "WAIT_REARM"
    )
    assert len(wait["levels"]) == 1
    assert wait["levels"][0]["target_price"] == "104"


def test_nonpositive_depth_level_is_not_presented_as_a_buyable_price():
    market = AccumulationMarket(HOUR, "1", "2", "2", "10", "0.1")
    wait = accumulation_wait_condition(
        market, AccumulationObservations(HOUR, 0), None, PARAMETERS, "WAIT_DEPTH"
    )
    assert wait["levels"] == []
    assert (
        accumulation_wait_condition(
            market, AccumulationObservations(HOUR, 0), None, PARAMETERS, "WAIT_ACCOUNT"
        )
        is None
    )


@pytest.mark.parametrize(
    ("guarded", "recovered", "target"),
    [(False, False, "100"), (True, False, "98"), (True, True, "100")],
)
def test_baseline_preview_combines_decline_depth_and_existing_spacing(
    guarded, recovered, target
):
    parameters = replace(PARAMETERS, timeframe="4h")
    market = AccumulationMarket(8 * HOUR, "100", "101", "110", "2", "5", False)
    guard = (
        AccumulationGuard(str(uuid4()), 8 * HOUR, "100", "2", 1, 1) if guarded else None
    )
    state = AccumulationObservations(
        8 * HOUR,
        1 if guarded else 0,
        high_close="105" if recovered else None,
        atr_at_high="2" if recovered else None,
        recovery_ready=recovered,
    )
    before = (market, state, guard)
    wait = accumulation_wait_condition(
        market, state, guard, parameters, "WAIT_BASELINE"
    )
    assert wait["reason"] == "WAIT_BASELINE" and wait["levels"] == []
    preview = wait["indicative"]
    assert preview["level"]["target_price"] == target
    assert preview["level"]["direction"] == (
        "below" if target == "100" else "at_or_below"
    )
    assert preview["conditions_match"] is False
    assert wait["next_close_ms"] == 12 * HOUR
    assert before == (market, state, guard)
    price = Decimal(target) - (Decimal("0.01") if target == "100" else Decimal(0))
    hypothetical = replace(
        market,
        close_ms=12 * HOUR,
        close=str(price),
        previous_close=market.close,
        severity=str((Decimal(market.peak) - price) / Decimal(market.atr)),
        conditions_match=True,
    )
    assert accumulation_signal_reason(
        hypothetical, state, guard, parameters
    ).startswith("BUY_")


def test_baseline_preview_respects_depth_and_rejects_nonpositive_boundaries():
    market = AccumulationMarket(HOUR, "109", "108", "110", "2", "0.5")
    state = AccumulationObservations(HOUR, 0)
    wait = accumulation_wait_condition(market, state, None, PARAMETERS, "WAIT_BASELINE")
    assert wait["indicative"]["level"]["target_price"] == "107.0"
    assert wait["indicative"]["conditions_match"] is True
    invalid = replace(market, peak="2", atr="10")
    assert "indicative" not in accumulation_wait_condition(
        invalid, state, None, PARAMETERS, "WAIT_BASELINE"
    )
