"""Pure recovery-target safety-order sizing and spacing helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

LEGACY_SIZING_MODE = "legacy_factors"
RECOVERY_SHADOW_MODE = "recovery_shadow"
RECOVERY_TARGET_MODE = "recovery_target"
TRADING_ATR_TIMEFRAME = "trading"
DEFAULT_RECOVERY_MAX_DEAL_QUOTE = 250.0
DEFAULT_EXECUTION_DRIFT_ATR_FRACTION = 0.25
DEFAULT_EXECUTION_DRIFT_MIN_PERCENT = 0.15
DEFAULT_EXECUTION_DRIFT_MAX_PERCENT = 0.5
RECOVERY_SIZING_MODES = frozenset(
    {
        LEGACY_SIZING_MODE,
        RECOVERY_SHADOW_MODE,
        RECOVERY_TARGET_MODE,
    }
)


def _float_value(value: Any, default: float) -> float:
    """Return a finite float or the supplied default."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return default
    return parsed


def _bool_value(value: Any, default: bool) -> bool:
    """Return a normalized bool for typed config and persisted JSON values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


@dataclass(frozen=True)
class RecoverySizingPolicy:
    """Immutable recovery-target DCA policy snapshotted for one deal."""

    mode: str = LEGACY_SIZING_MODE
    atr_timeframe: str = "1h"
    atr_length: int = 14
    spacing_atr_multiplier: float = 3.0
    minimum_spacing_percent: float = 5.0
    spacing_step_scale: float = 1.6
    recovery_atr_multiplier: float = 5.5
    minimum_recovery_percent: float = 12.0
    maximum_recovery_percent: float = 30.0
    maximum_deal_quote: float = DEFAULT_RECOVERY_MAX_DEAL_QUOTE
    minimum_tp_improvement_percent: float = 5.0
    execution_guard_enabled: bool = True
    execution_drift_atr_fraction: float = DEFAULT_EXECUTION_DRIFT_ATR_FRACTION
    execution_drift_min_percent: float = DEFAULT_EXECUTION_DRIFT_MIN_PERCENT
    execution_drift_max_percent: float = DEFAULT_EXECUTION_DRIFT_MAX_PERCENT

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible policy snapshot."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "RecoverySizingPolicy":
        """Build a normalized policy from persisted JSON data."""
        values = payload or {}
        normalized_mode = normalize_recovery_sizing_mode(values.get("mode"))
        try:
            atr_length = max(2, int(values.get("atr_length", 14)))
        except (TypeError, ValueError):
            atr_length = 14
        minimum_recovery = max(
            0.0,
            _float_value(values.get("minimum_recovery_percent"), 12.0),
        )
        maximum_recovery = max(
            minimum_recovery,
            _float_value(values.get("maximum_recovery_percent"), 30.0),
        )
        execution_drift_min = max(
            0.0,
            _float_value(
                values.get("execution_drift_min_percent"),
                DEFAULT_EXECUTION_DRIFT_MIN_PERCENT,
            ),
        )
        execution_drift_max = max(
            execution_drift_min,
            _float_value(
                values.get("execution_drift_max_percent"),
                DEFAULT_EXECUTION_DRIFT_MAX_PERCENT,
            ),
        )
        return cls(
            mode=normalized_mode,
            atr_timeframe=str(values.get("atr_timeframe") or "1h").strip() or "1h",
            atr_length=atr_length,
            spacing_atr_multiplier=max(
                0.0,
                _float_value(values.get("spacing_atr_multiplier"), 3.0),
            ),
            minimum_spacing_percent=max(
                0.0,
                _float_value(values.get("minimum_spacing_percent"), 5.0),
            ),
            spacing_step_scale=max(
                1.0,
                _float_value(values.get("spacing_step_scale"), 1.6),
            ),
            recovery_atr_multiplier=max(
                0.0,
                _float_value(values.get("recovery_atr_multiplier"), 5.5),
            ),
            minimum_recovery_percent=minimum_recovery,
            maximum_recovery_percent=maximum_recovery,
            maximum_deal_quote=max(
                0.0,
                _float_value(
                    values.get("maximum_deal_quote"),
                    DEFAULT_RECOVERY_MAX_DEAL_QUOTE,
                ),
            ),
            minimum_tp_improvement_percent=max(
                0.0,
                _float_value(
                    values.get("minimum_tp_improvement_percent"),
                    5.0,
                ),
            ),
            execution_guard_enabled=_bool_value(
                values.get("execution_guard_enabled"),
                True,
            ),
            execution_drift_atr_fraction=max(
                0.0,
                _float_value(
                    values.get("execution_drift_atr_fraction"),
                    DEFAULT_EXECUTION_DRIFT_ATR_FRACTION,
                ),
            ),
            execution_drift_min_percent=execution_drift_min,
            execution_drift_max_percent=execution_drift_max,
        )


@dataclass(frozen=True)
class RecoverySizingResult:
    """Outcome of sizing one recovery-target safety-order candidate."""

    requested_quote: float
    final_quote: float
    current_tp_price: float
    current_recovery_percent: float
    target_recovery_percent: float
    projected_average_price: float
    projected_tp_price: float
    projected_recovery_percent: float
    tp_improvement_percent: float
    remaining_deal_quote: float
    capped: bool
    should_place: bool
    reason: str

    def to_dict(self) -> dict[str, float | bool | str]:
        """Return a JSON-compatible diagnostic payload."""
        return asdict(self)


def normalize_recovery_sizing_mode(value: Any) -> str:
    """Return a supported recovery-sizing mode, defaulting to legacy."""
    normalized = str(value or "").strip().lower()
    if normalized in RECOVERY_SIZING_MODES:
        return normalized
    return LEGACY_SIZING_MODE


def resolve_recovery_atr_timeframe(
    config: dict[str, Any],
    *,
    trading_timeframe: str | None = None,
) -> str:
    """Resolve the ATR candle interval, inheriting the trading interval by default."""
    configured = str(
        config.get("dynamic_so_atr_timeframe", TRADING_ATR_TIMEFRAME) or ""
    ).strip()
    if configured.lower() not in {
        "",
        TRADING_ATR_TIMEFRAME,
        "inherit",
        "same_as_trading",
    }:
        return configured

    inherited = str(trading_timeframe or config.get("timeframe") or "1h").strip()
    return inherited or "1h"


def build_recovery_sizing_policy(
    config: dict[str, Any],
    *,
    trading_timeframe: str | None = None,
) -> RecoverySizingPolicy:
    """Build the per-deal recovery policy from a runtime config snapshot."""
    atr_timeframe = resolve_recovery_atr_timeframe(
        config,
        trading_timeframe=trading_timeframe,
    )
    values = {
        "mode": config.get("dynamic_so_sizing_mode", LEGACY_SIZING_MODE),
        "atr_timeframe": atr_timeframe,
        "atr_length": config.get("dynamic_so_atr_length", 14),
        "spacing_atr_multiplier": config.get(
            "dynamic_so_spacing_atr_multiplier",
            3.0,
        ),
        "minimum_spacing_percent": config.get("sos", 5.0),
        "spacing_step_scale": config.get("ss", 1.6),
        "recovery_atr_multiplier": config.get(
            "dynamic_so_recovery_atr_multiplier",
            5.5,
        ),
        "minimum_recovery_percent": config.get(
            "dynamic_so_recovery_min_pct",
            12.0,
        ),
        "maximum_recovery_percent": config.get(
            "dynamic_so_recovery_max_pct",
            30.0,
        ),
        "maximum_deal_quote": config.get(
            "dynamic_so_max_deal_quote",
            DEFAULT_RECOVERY_MAX_DEAL_QUOTE,
        ),
        "minimum_tp_improvement_percent": config.get(
            "dynamic_so_min_tp_improvement_pct",
            5.0,
        ),
        "execution_guard_enabled": config.get(
            "dynamic_so_execution_guard_enabled",
            True,
        ),
        "execution_drift_atr_fraction": config.get(
            "dynamic_so_execution_drift_atr_fraction",
            DEFAULT_EXECUTION_DRIFT_ATR_FRACTION,
        ),
        "execution_drift_min_percent": config.get(
            "dynamic_so_execution_drift_min_pct",
            DEFAULT_EXECUTION_DRIFT_MIN_PERCENT,
        ),
        "execution_drift_max_percent": config.get(
            "dynamic_so_execution_drift_max_pct",
            DEFAULT_EXECUTION_DRIFT_MAX_PERCENT,
        ),
    }
    return RecoverySizingPolicy.from_dict(values)


def calculate_recovery_target_percent(
    atr_percent: float,
    policy: RecoverySizingPolicy,
) -> float:
    """Return the desired post-order distance from fill price to TP."""
    atr_target = max(0.0, atr_percent) * policy.recovery_atr_multiplier
    return min(
        policy.maximum_recovery_percent,
        max(policy.minimum_recovery_percent, atr_target),
    )


def calculate_recovery_spacing_percent(
    reference_atr_percent: float,
    filled_safety_orders: int,
    policy: RecoverySizingPolicy,
) -> float:
    """Return required price spacing below the preceding filled buy."""
    base_gap = max(
        policy.minimum_spacing_percent,
        max(0.0, reference_atr_percent) * policy.spacing_atr_multiplier,
    )
    return base_gap * (policy.spacing_step_scale ** max(0, filled_safety_orders))


def calculate_recovery_trigger_price(
    reference_price: float,
    spacing_percent: float,
) -> float:
    """Return the absolute price that arms the next recovery SO."""
    if reference_price <= 0:
        return 0.0
    normalized_spacing = min(99.999999, max(0.0, spacing_percent))
    return reference_price * (1 - (normalized_spacing / 100.0))


def calculate_recovery_execution_drift_percent(
    atr_percent: float,
    policy: RecoverySizingPolicy,
) -> float:
    """Return the ATR-scaled price drift allowed between trigger and execution."""
    if not policy.execution_guard_enabled:
        return 0.0
    atr_drift = max(0.0, atr_percent) * policy.execution_drift_atr_fraction
    return min(
        policy.execution_drift_max_percent,
        max(policy.execution_drift_min_percent, atr_drift),
    )


def calculate_recovery_execution_ceiling(
    trigger_price: float,
    atr_percent: float,
    policy: RecoverySizingPolicy,
) -> float:
    """Return the highest acceptable recovery safety-order buy price."""
    if trigger_price <= 0 or not policy.execution_guard_enabled:
        return 0.0
    drift_percent = calculate_recovery_execution_drift_percent(
        atr_percent,
        policy,
    )
    return trigger_price * (1 + (drift_percent / 100.0))


def calculate_projected_average_price(
    total_cost: float,
    total_amount: float,
    fill_price: float,
    quote_amount: float,
    fee_ratio: float,
) -> float:
    """Return the fee-adjusted average after a hypothetical quote buy."""
    if total_amount <= 0 or fill_price <= 0:
        return 0.0
    normalized_quote = max(0.0, quote_amount)
    projected_amount = total_amount + (normalized_quote / fill_price)
    if projected_amount <= 0:
        return 0.0
    projected_cost = max(0.0, total_cost) + normalized_quote
    return projected_cost * (1 + max(0.0, fee_ratio)) / projected_amount


def calculate_recovery_sizing(
    *,
    total_cost: float,
    total_amount: float,
    fill_price: float,
    take_profit_percent: float,
    fee_ratio: float,
    atr_percent: float,
    policy: RecoverySizingPolicy,
    minimum_order_quote: float = 0.0,
    maximum_available_quote: float | None = None,
) -> RecoverySizingResult:
    """Calculate a budget-aware quote order for a target TP recovery distance."""
    if total_cost <= 0 or total_amount <= 0 or fill_price <= 0:
        return _empty_result("invalid_trade_state")
    if policy.mode == RECOVERY_TARGET_MODE and policy.maximum_deal_quote <= 0:
        return _empty_result("missing_deal_budget")

    normalized_fee = max(0.0, fee_ratio)
    normalized_tp = max(0.0, take_profit_percent)
    current_average = total_cost * (1 + normalized_fee) / total_amount
    current_tp = current_average * (1 + (normalized_tp / 100.0))
    current_recovery = ((current_tp / fill_price) - 1) * 100
    target_recovery = calculate_recovery_target_percent(atr_percent, policy)
    remaining_deal_limit = (
        max(0.0, policy.maximum_deal_quote - total_cost)
        if policy.maximum_deal_quote > 0
        else float("inf")
    )
    remaining_deal_quote = (
        remaining_deal_limit if policy.maximum_deal_quote > 0 else -1.0
    )

    if current_recovery <= target_recovery:
        return RecoverySizingResult(
            requested_quote=0.0,
            final_quote=0.0,
            current_tp_price=current_tp,
            current_recovery_percent=current_recovery,
            target_recovery_percent=target_recovery,
            projected_average_price=current_average,
            projected_tp_price=current_tp,
            projected_recovery_percent=current_recovery,
            tp_improvement_percent=0.0,
            remaining_deal_quote=remaining_deal_quote,
            capped=False,
            should_place=False,
            reason="tp_already_reachable",
        )

    target_tp = fill_price * (1 + (target_recovery / 100.0))
    target_average = target_tp / (1 + (normalized_tp / 100.0))
    denominator = (target_average / fill_price) - (1 + normalized_fee)
    numerator = (total_cost * (1 + normalized_fee)) - (target_average * total_amount)
    requested_quote = numerator / denominator if denominator > 0 else 0.0
    requested_quote = max(0.0, requested_quote)
    if requested_quote <= 0:
        return _empty_result(
            "target_not_solvable",
            current_tp=current_tp,
            current_recovery=current_recovery,
            target_recovery=target_recovery,
            current_average=current_average,
            remaining_deal_quote=remaining_deal_quote,
        )

    desired_quote = max(requested_quote, max(0.0, minimum_order_quote))
    available_limits = [remaining_deal_limit]
    if maximum_available_quote is not None:
        available_limits.append(max(0.0, maximum_available_quote))
    final_quote = min(desired_quote, *available_limits)
    capped = final_quote + 1e-12 < desired_quote

    projected_average = calculate_projected_average_price(
        total_cost,
        total_amount,
        fill_price,
        final_quote,
        normalized_fee,
    )
    projected_tp = projected_average * (1 + (normalized_tp / 100.0))
    projected_recovery = ((projected_tp / fill_price) - 1) * 100
    improvement = max(0.0, current_recovery - projected_recovery)

    if final_quote <= 0:
        reason = "deal_budget_exhausted"
        should_place = False
    elif final_quote + 1e-12 < minimum_order_quote:
        reason = "below_exchange_minimum"
        should_place = False
    elif capped and improvement < policy.minimum_tp_improvement_percent:
        reason = "insufficient_tp_improvement"
        should_place = False
    else:
        reason = "budget_capped" if capped else "target_recovery"
        should_place = True

    return RecoverySizingResult(
        requested_quote=requested_quote,
        final_quote=final_quote,
        current_tp_price=current_tp,
        current_recovery_percent=current_recovery,
        target_recovery_percent=target_recovery,
        projected_average_price=projected_average,
        projected_tp_price=projected_tp,
        projected_recovery_percent=projected_recovery,
        tp_improvement_percent=improvement,
        remaining_deal_quote=remaining_deal_quote,
        capped=capped,
        should_place=should_place,
        reason=reason,
    )


def _empty_result(
    reason: str,
    *,
    current_tp: float = 0.0,
    current_recovery: float = 0.0,
    target_recovery: float = 0.0,
    current_average: float = 0.0,
    remaining_deal_quote: float = 0.0,
) -> RecoverySizingResult:
    """Return a normalized non-order result."""
    return RecoverySizingResult(
        requested_quote=0.0,
        final_quote=0.0,
        current_tp_price=current_tp,
        current_recovery_percent=current_recovery,
        target_recovery_percent=target_recovery,
        projected_average_price=current_average,
        projected_tp_price=current_tp,
        projected_recovery_percent=current_recovery,
        tp_improvement_percent=0.0,
        remaining_deal_quote=remaining_deal_quote,
        capped=False,
        should_place=False,
        reason=reason,
    )
