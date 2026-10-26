"""Deterministic equal-funding replay with live pure-strategy calculations."""

from dataclasses import asdict
from decimal import Decimal

import pytest
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_replay import replay_accumulation
from service.accumulation_strategy import (
    AccumulationCandle,
    AccumulationParameters,
    accumulation_requested_quote,
    accumulation_step_severity,
    calculate_accumulation_market,
)


def replay_fixture():
    parameters = AccumulationParameters()
    candles = []
    for index in range(parameters.history_length + 50):
        price = (
            Decimal(100)
            if index < parameters.history_length
            else Decimal(100) - Decimal(index - parameters.history_length)
        )
        candles.append(
            asdict(
                AccumulationCandle(
                    (index + 1) * parameters.interval_ms,
                    str(price + 1),
                    str(price + 2),
                    str(price - 1),
                    str(price),
                )
            )
        )
    return parameters, {
        "candles": candles,
        "funding": "1000",
        "fee_bps": "10",
        "slippage_bps": "20",
        "fixed_interval_candles": 5,
    }


def test_replay_preserves_budget_fees_and_equal_funding_without_account_access():
    parameters, payload = replay_fixture()
    report = replay_accumulation(payload, parameters)
    assert report == replay_accumulation(payload, parameters)
    assert report["simulation_only"] and report["gap_count"] == 0
    assert report["accumulation_trades"]
    for result in report["results"]:
        assert Decimal(result["contributed_quote"]) == 1000
        assert Decimal(result["cash_quote"]) >= 0
        assert abs(
            Decimal(result["spent_quote_including_fees"])
            + Decimal(result["cash_quote"])
            - 1000
        ) < Decimal("1e-40")
        assert Decimal(result["fees_quote"]) > 0
        assert 0 <= Decimal(result["maximum_drawdown_fraction"]) <= 1
    first = report["accumulation_trades"][0]
    index = next(
        i
        for i, row in enumerate(payload["candles"])
        if row["close_ms"] == first["signal_close_ms"]
    )
    market = calculate_accumulation_market(
        [
            AccumulationCandle(**row)
            for row in payload["candles"][
                index - parameters.history_length + 1 : index + 1
            ]
        ],
        parameters,
        close_ms=first["signal_close_ms"],
    )
    _, principal = accumulation_requested_quote(
        accumulation_step_severity(
            market.close, market.previous_close, market.atr, None, parameters
        ),
        "1000",
        parameters,
    )
    assert Decimal(first["spent"]) == Decimal(principal)
    assert first["execution_open_ms"] == first["signal_close_ms"]


def test_future_prices_cannot_change_earlier_replay_fills():
    parameters, payload = replay_fixture()
    original = replay_accumulation(payload, parameters)
    last = payload["candles"][-1]
    last.update(open="10000", high="10002", low="9999", close="10000")
    changed = replay_accumulation(payload, parameters)
    assert original["accumulation_trades"][:-1] == changed["accumulation_trades"][:-1]


def test_gaps_cancel_pending_signals_and_require_contiguous_warmup():
    parameters, payload = replay_fixture()
    for row in payload["candles"][parameters.history_length + 10 :]:
        row["close_ms"] += parameters.interval_ms
    report = replay_accumulation(payload, parameters)
    assert report["gap_count"] == 1 and report["signal_counts"]["WAIT_DATA"] > 0
    gap_start = (
        payload["candles"][parameters.history_length + 10]["close_ms"]
        - parameters.interval_ms
    )
    assert all(
        row["execution_open_ms"] < gap_start for row in report["accumulation_trades"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("fee_bps", "1001"),
        ("slippage_bps", "NaN"),
        ("funding", "0"),
        ("fixed_interval_candles", True),
        ("candles", []),
    ],
)
def test_replay_rejects_unbounded_or_invalid_inputs(field, value):
    parameters, payload = replay_fixture()
    payload[field] = value
    with pytest.raises(AccumulationStateError):
        replay_accumulation(payload, parameters)


def test_only_one_historical_comparison_owns_cpu_even_if_its_http_client_disappears():
    from service.accumulation_replay import _REPLAY_SLOT, run_accumulation_replay
    from service.accumulation_state import AccumulationConflictError

    parameters, payload = replay_fixture()
    assert _REPLAY_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(AccumulationConflictError, match="already running"):
            run_accumulation_replay(payload, parameters)
    finally:
        _REPLAY_SLOT.release()
    assert run_accumulation_replay(payload, parameters)["simulation_only"]


def test_fixed_interval_benchmark_keeps_calendar_schedule_across_missing_candles():
    parameters, payload = replay_fixture()
    del payload["candles"][parameters.history_length + 5]
    result = replay_accumulation(payload, parameters)
    fixed = next(
        row for row in result["results"] if row["strategy"] == "fixed_interval_dca"
    )
    assert fixed["buy_count"] == 9
    assert abs(Decimal(fixed["cash_quote"]) - 100) < Decimal("1e-40")
