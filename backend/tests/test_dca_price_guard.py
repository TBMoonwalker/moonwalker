"""Pure branch coverage for the exit price guard and PnL inversion."""

import pytest
from service.dca.decision import (
    EXIT_GUARD_MAX_PRICE_REASONS,
    EXIT_GUARD_MIN_PRICE_REASONS,
    evaluate_exit_price_guard,
)
from service.dca.math import calculate_pnl_break_even_price


@pytest.mark.parametrize(
    "sell_reason, min_price, max_price, fresh_price, expected",
    [
        ("take_profit", 110.0, None, 111.0, (True, "exit_price_ok")),
        ("take_profit", 110.0, None, 110.0, (True, "exit_price_ok")),
        ("take_profit", 110.0, None, 109.99, (False, "fresh_price_below_min")),
        ("trailing_take_profit", 109.0, None, 109.0, (True, "exit_price_ok")),
        ("trailing_take_profit", 109.0, None, 108.99, (False, "fresh_price_below_min")),
        ("autopilot_timeout", 95.0, None, 95.0, (True, "exit_price_ok")),
        ("autopilot_timeout", 95.0, None, 94.0, (False, "fresh_price_below_min")),
        ("stop_loss", None, 95.0, 94.0, (True, "exit_price_ok")),
        ("stop_loss", None, 95.0, 95.0, (True, "exit_price_ok")),
        ("stop_loss", None, 95.0, 95.01, (False, "fresh_price_above_max")),
    ],
)
def test_guard_bounds(
    sell_reason: str,
    min_price: float | None,
    max_price: float | None,
    fresh_price: float,
    expected: tuple[bool, str],
) -> None:
    assert (
        evaluate_exit_price_guard(
            sell_reason=sell_reason,
            fresh_price=fresh_price,
            min_price=min_price,
            max_price=max_price,
        )
        == expected
    )


@pytest.mark.parametrize(
    "sell_reason, min_price, max_price",
    [
        ("take_profit", None, None),
        ("take_profit", None, 95.0),
        ("trailing_take_profit", None, None),
        ("autopilot_timeout", None, None),
        ("stop_loss", 110.0, None),
        ("stop_loss", None, None),
        ("stop_loss", 110.0, 95.0),
        ("manual_sell", 110.0, None),
        ("", 110.0, None),
        (None, 110.0, None),
    ],
)
def test_guard_fails_closed_on_unavailable_configuration(
    sell_reason: str | None,
    min_price: float | None,
    max_price: float | None,
) -> None:
    assert evaluate_exit_price_guard(
        sell_reason=sell_reason or "",
        fresh_price=100.0,
        min_price=min_price,
        max_price=max_price,
    ) == (False, "guard_unavailable")


def test_guard_fails_closed_on_missing_fresh_price() -> None:
    assert evaluate_exit_price_guard(
        sell_reason="take_profit",
        fresh_price=None,
        min_price=110.0,
    ) == (False, "guard_unavailable")


def test_guard_reason_sets_are_disjoint() -> None:
    assert EXIT_GUARD_MIN_PRICE_REASONS & EXIT_GUARD_MAX_PRICE_REASONS == frozenset()


def test_pnl_break_even_price_round_trips_the_pnl_formula() -> None:
    price = calculate_pnl_break_even_price(108.5, 8.5, 9.0)
    assert price == pytest.approx(109.0)

    reference = calculate_pnl_break_even_price(97.0, -3.0, -5.0)
    assert reference == pytest.approx(95.0)


def test_pnl_break_even_price_recovers_reference_price_at_same_pnl() -> None:
    price = calculate_pnl_break_even_price(108.5, 8.5, 8.5)
    assert price == pytest.approx(108.5)


@pytest.mark.parametrize(
    "reference_price, reference_pnl",
    [
        (0.0, 5.0),
        (100.0, -100.0),
        (100.0, -120.0),
    ],
)
def test_pnl_break_even_price_rejects_degenerate_inputs(
    reference_price: float,
    reference_pnl: float,
) -> None:
    assert calculate_pnl_break_even_price(reference_price, reference_pnl, 0.0) is None
