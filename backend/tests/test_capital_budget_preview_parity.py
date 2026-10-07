"""Cross-language parity pin for the capital-budget preview.

The frontend helper ``frontend/src/helpers/capitalBudgetPreview.ts`` mirrors the
baseline reserve, incremental base-order budget, and buffer normalization of
``service.capital_budget_logic`` so the capital-settings preview stays in lockstep
with the admission gate in ``evaluate_capital_budget``.

This contract test recomputes the same shared numeric vectors the frontend test
(``frontend/tests-vitest/capital-budget-preview.test.ts``) asserts, using the
backend primitives. If a future edit changes the backend math, this test fails,
signaling that the frontend mirror must be updated; the frontend's own test fails
on its side if it drifts. The two together pin the shared formula.

Documented boundaries (intentional, not defects):
- Rounding: JS Math.round(x*1e8)/1e8 (half-up) and Python round(x, 8) (banker's)
   agree on every realistic money value; they can disagree only on exact
   8th-decimal ties, which these vectors deliberately avoid.
- Data source: the preview reads the live ``openTrades`` feed, whereas the gate
   reads ``model.OpenTrades``. The preview is display-only and never gates
   execution; on disconnect it shows "unavailable" instead of a stale reserve.
- Gate vs preview: the frontend applies the buffer only while dynamic DCA is on,
   but the config load flow forces the buffer to 0 when dynamic DCA is off, so
   the two agree for every value the preview can show.
"""

import service.capital_budget_logic as cb

# Shared draft, matching frontend/tests-vitest/capital-budget-preview.test.ts:
# base order 12 USDC, max safety orders 5, reserve on, buffer 30% (API ratio 0.30),
# dynamic DCA on. "bo" mirrors the frontend baseOrderSize used for open-deal
# reserves; the new-deal vectors pass the base explicitly.
_DRAFT_CONFIG = {
    "capital_max_fund": 2500.0,
    "capital_reserve_safety_orders": True,
    "capital_budget_buffer_pct": 30,
    "dynamic_dca": True,
    "bo": 12.0,
    "mstc": 5,
}
_BASE = 12.0
_MIXED_OPEN_TRADES = [
    {"so_count": 2},
    {"so_count": 5},
    {"so_count": 6},
    {"so_count": 0, "unsellable_amount": 1.0, "unsellable_reason": "dust"},
]


def _requirement(buffer_value: object, reserve: bool) -> float:
    """Return the backend required_quote for a base order at the given buffer."""
    config = {
        **_DRAFT_CONFIG,
        "capital_budget_buffer_pct": buffer_value,
        "capital_reserve_safety_orders": reserve,
    }
    check = cb.evaluate_capital_budget(
        config,
        {"symbol": "NIL/USDC", "ordersize": _BASE, "baseorder": True},
        funds_locked=0.0,
        open_trade_reserve=0.0,
        pending_quote=0.0,
        closed_profit=0.0,
    )
    assert check.required_quote is not None
    return check.required_quote


def test_new_deal_reserve_matches_frontend_field() -> None:
    # newDealReserve = base * maxSafetyOrders
    assert (
        cb.estimate_remaining_trade_reserve(_DRAFT_CONFIG, 0, base_order_size=_BASE)
        == 60.0
    )


def test_new_deal_baseline_matches_frontend_field() -> None:
    # newDealBaseline = base + reserve = base * (1 + maxSafetyOrders)
    assert cb.estimate_full_trade_budget(_DRAFT_CONFIG, _BASE) == 72.0


def test_new_deal_requirement_with_buffer_matches_frontend_field() -> None:
    # newDealRequirement = round(72 * 1.30, 8); 30 and 0.3 both normalize to 0.3.
    assert _requirement(30, True) == 93.6
    assert _requirement(0.3, True) == 93.6


def test_disabled_reserve_requirement_matches_frontend_field() -> None:
    # reserve off -> requirement is the buffered baseline only: round(12 * 1.30, 8)
    assert _requirement(30, False) == 15.6


def test_open_deal_reserve_matches_frontend_field() -> None:
    # openDealReserve = base * sum(max(0, mstc - so_count)) over 30 live deals.
    assert (
        cb.estimate_open_trade_reserve(
            _DRAFT_CONFIG, [{"so_count": 0} for _ in range(30)]
        )
        == 1800.0
    )


def test_open_deal_reserve_skips_used_exhausted_and_unsellable() -> None:
    # remaining = (5-2) only; unsellable dust row is skipped; reserve = 12 * 3.
    assert cb.estimate_open_trade_reserve(_DRAFT_CONFIG, _MIXED_OPEN_TRADES) == 36.0


def test_zero_deals_reserve_is_zero() -> None:
    assert cb.estimate_open_trade_reserve(_DRAFT_CONFIG, []) == 0.0


def test_disabled_reserve_open_deal_reserve_is_zero() -> None:
    assert (
        cb.estimate_open_trade_reserve(
            {**_DRAFT_CONFIG, "capital_reserve_safety_orders": False},
            [{"so_count": 0} for _ in range(30)],
        )
        == 0.0
    )


def test_buffer_normalization_matches_frontend_convention() -> None:
    # 30 and 0.3 both normalize to a 0.30 buffer; "2" is 0.02.
    assert cb.normalize_buffer_pct(30) == 0.3
    assert cb.normalize_buffer_pct(0.3) == 0.3
    assert cb.normalize_buffer_pct("2") == 0.02


def test_negative_buffer_clamps_like_frontend() -> None:
    # The frontend clamps a negative buffer to no buffer; normalize_buffer_pct
    # does the same, keeping the two in lockstep.
    assert _requirement(-5, True) == 72.0
    assert cb.normalize_buffer_pct(-5.0) == 0.0
    assert cb.normalize_buffer_pct(0) == 0.0
