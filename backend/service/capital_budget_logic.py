"""Pure helpers for global capital-budget guardrails."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

EPSILON = 1e-12


@dataclass(frozen=True)
class CapitalBudgetSettings:
    """Normalized capital-budget settings from runtime config."""

    configured: bool
    principal_limit: float
    reserve_safety_orders: bool
    buffer_pct: float
    autopilot_active: bool
    profit_stretch_enabled: bool
    profit_stretch_ratio: float
    profit_stretch_max: float
    entry_stretch_max_multiplier: float
    safety_stretch_max_multiplier: float


@dataclass(frozen=True)
class CapitalBudgetCheck:
    """Result of checking one proposed buy against the capital budget."""

    ok: bool
    reason: str
    symbol: str
    order_quote: float | None
    required_quote: float | None
    available_quote: float | None
    principal_limit: float
    effective_limit: float
    stretch_quote: float
    funds_locked: float
    open_trade_reserve: float
    pending_quote: float
    projected_total: float | None
    buffer_pct: float
    reserve_safety_orders: bool

    def to_precheck_result(self) -> dict[str, Any]:
        """Return a normalized precheck payload for shared buy-failure handling."""
        result: dict[str, Any] = {
            "ok": self.ok,
            "reason": self.reason,
            "symbol": self.symbol,
            "available_quote": (
                round(float(self.available_quote), 8)
                if self.available_quote is not None
                else None
            ),
            "capital_principal_limit": round(float(self.principal_limit), 8),
            "capital_effective_limit": round(float(self.effective_limit), 8),
            "capital_stretch_quote": round(float(self.stretch_quote), 8),
            "capital_funds_locked": round(float(self.funds_locked), 8),
            "capital_open_trade_reserve": round(float(self.open_trade_reserve), 8),
            "capital_pending_quote": round(float(self.pending_quote), 8),
            "capital_reserve_safety_orders": self.reserve_safety_orders,
        }
        if self.order_quote is not None:
            result["order_quote"] = round(float(self.order_quote), 8)
        if self.required_quote is not None:
            result["required_quote"] = round(float(self.required_quote), 8)
        if self.projected_total is not None:
            result["capital_projected_total"] = round(float(self.projected_total), 8)
        if self.buffer_pct:
            result["buffer_pct"] = round(float(self.buffer_pct), 6)
        return result


def to_bool(value: Any, default: bool = False) -> bool:
    """Normalize bool-like config values."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", "none", "null", ""}:
        return False
    return bool(value)


def to_int(value: Any, default: int = 0) -> int:
    """Normalize int-like config values while preserving explicit zero."""
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    """Normalize float-like config values while preserving explicit zero."""
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return default


def normalize_buffer_pct(value: Any) -> float:
    """Normalize ratio-style or whole-percent budget buffers.

    Older API payloads may send `0.5` for 50%, while the UI labels the field as
    a percentage and naturally leads operators to enter `50`. Accept both.
    """
    buffer_pct = to_float(value, 0.0)
    if buffer_pct <= 0:
        return 0.0
    if buffer_pct > 1:
        return buffer_pct / 100
    return buffer_pct


def has_capital_budget_config(config: dict[str, Any]) -> bool:
    """Return whether this config snapshot carries a capital limit key."""
    return "capital_max_fund" in config or "autopilot_max_fund" in config


def resolve_capital_max_fund(config: dict[str, Any]) -> float:
    """Return the canonical capital limit with legacy-key fallback."""
    if "capital_max_fund" in config:
        return to_float(config.get("capital_max_fund"), 0.0)
    return to_float(config.get("autopilot_max_fund"), 0.0)


def build_capital_budget_settings(
    config: dict[str, Any],
) -> CapitalBudgetSettings:
    """Build normalized capital-budget settings from raw config."""
    buffer_value = (
        config.get("capital_budget_buffer_pct")
        if "capital_budget_buffer_pct" in config
        else config.get("buy_fund_buffer_pct")
    )
    buffer_pct = normalize_buffer_pct(buffer_value)
    return CapitalBudgetSettings(
        configured=has_capital_budget_config(config),
        principal_limit=resolve_capital_max_fund(config),
        reserve_safety_orders=to_bool(
            config.get("capital_reserve_safety_orders"),
            default=True,
        ),
        buffer_pct=buffer_pct,
        autopilot_active=to_bool(config.get("autopilot"), default=False),
        profit_stretch_enabled=to_bool(
            config.get("autopilot_profit_stretch_enabled"),
            default=False,
        ),
        profit_stretch_ratio=max(
            0.0,
            to_float(config.get("autopilot_profit_stretch_ratio"), 0.0),
        ),
        profit_stretch_max=max(
            0.0,
            to_float(config.get("autopilot_profit_stretch_max"), 0.0),
        ),
        entry_stretch_max_multiplier=max(
            1.0,
            to_float(config.get("autopilot_entry_stretch_max_multiplier"), 1.0),
        ),
        safety_stretch_max_multiplier=max(
            1.0,
            to_float(config.get("autopilot_safety_stretch_max_multiplier"), 1.0),
        ),
    )


def calculate_profit_stretch(
    settings: CapitalBudgetSettings,
    closed_profit: float,
) -> float:
    """Return realized-profit stretch allowed above the hard principal limit."""
    if (
        not settings.autopilot_active
        or not settings.profit_stretch_enabled
        or settings.profit_stretch_ratio <= 0
        or settings.profit_stretch_max <= 0
    ):
        return 0.0
    earned_stretch = max(0.0, float(closed_profit or 0.0)) * (
        settings.profit_stretch_ratio
    )
    return round(min(earned_stretch, settings.profit_stretch_max), 8)


def calculate_effective_capital_limit(
    settings: CapitalBudgetSettings,
    closed_profit: float,
) -> tuple[float, float]:
    """Return effective limit and stretch quote."""
    stretch_quote = calculate_profit_stretch(settings, closed_profit)
    return round(settings.principal_limit + stretch_quote, 8), stretch_quote


def estimate_remaining_trade_reserve(
    config: dict[str, Any],
    so_count: int,
    *,
    base_order_size: float | None = None,
) -> float:
    """Estimate remaining future safety-order budget for one open trade."""
    max_safety_orders = max(0, to_int(config.get("mstc"), 0))
    remaining_orders = max(0, max_safety_orders - max(0, int(so_count or 0)))
    if remaining_orders <= 0:
        return 0.0

    if to_bool(config.get("dynamic_dca"), default=False):
        unit_cost = (
            max(0.0, float(base_order_size))
            if base_order_size is not None
            else max(0.0, to_float(config.get("bo"), 0.0))
        )
        return round(unit_cost * remaining_orders, 8)

    safety_order_size = max(0.0, to_float(config.get("so"), 0.0))
    if safety_order_size <= 0:
        return 0.0

    volume_scale = to_float(config.get("os"), 1.0)
    if volume_scale <= 0:
        volume_scale = 1.0

    reserve = 0.0
    for order_index in range(max(0, int(so_count or 0)), max_safety_orders):
        reserve += safety_order_size * (volume_scale**order_index)
    return round(reserve, 8)


def estimate_open_trade_reserve(
    config: dict[str, Any],
    open_trades: Iterable[dict[str, Any]],
) -> float:
    """Estimate remaining future safety-order budget for active open trades."""
    settings = build_capital_budget_settings(config)
    if not settings.reserve_safety_orders:
        return 0.0

    total = 0.0
    for open_trade in open_trades:
        if float(open_trade.get("unsellable_amount") or 0.0) > 0 and open_trade.get(
            "unsellable_reason"
        ):
            continue
        total += estimate_remaining_trade_reserve(
            config,
            to_int(open_trade.get("so_count"), 0),
        )
    return round(total, 8)


def estimate_full_trade_budget(
    config: dict[str, Any],
    entry_order_size: float,
) -> float:
    """Estimate base order plus future safety-order budget for a new trade."""
    order_size = max(0.0, float(entry_order_size or 0.0))
    return round(
        order_size
        + estimate_remaining_trade_reserve(config, 0, base_order_size=order_size),
        8,
    )


def resolve_order_quote(order: dict[str, Any]) -> float | None:
    """Return the proposed buy quote amount for an order payload."""
    quote = to_float(order.get("ordersize"), 0.0)
    return quote if quote > 0 else None


def _resolve_safety_order_budget_delta(
    config: dict[str, Any],
    order: dict[str, Any],
    order_quote: float,
) -> float:
    """Return unreserved budget needed by a safety-order execution."""
    order_count = max(1, to_int(order.get("order_count"), 1))
    before_count = max(0, order_count - 1)
    before_reserve = estimate_remaining_trade_reserve(config, before_count)
    after_reserve = estimate_remaining_trade_reserve(config, order_count)
    reserved_for_order = max(0.0, before_reserve - after_reserve)
    return round(max(0.0, order_quote - reserved_for_order), 8)


def calculate_order_budget_requirement(
    config: dict[str, Any],
    order: dict[str, Any],
    *,
    settings: CapitalBudgetSettings | None = None,
) -> tuple[float | None, float | None]:
    """Return order quote and incremental capital requirement for a buy order."""
    order_quote = resolve_order_quote(order)
    if order_quote is None:
        return None, None

    resolved_settings = settings or build_capital_budget_settings(config)
    if not resolved_settings.reserve_safety_orders:
        return order_quote, order_quote

    if to_bool(order.get("baseorder"), default=False):
        return order_quote, estimate_full_trade_budget(config, order_quote)

    if to_bool(order.get("safetyorder"), default=False):
        return order_quote, _resolve_safety_order_budget_delta(
            config,
            order,
            order_quote,
        )

    return order_quote, order_quote


def evaluate_capital_budget(
    config: dict[str, Any],
    order: dict[str, Any],
    *,
    funds_locked: float,
    open_trade_reserve: float,
    pending_quote: float,
    closed_profit: float,
) -> CapitalBudgetCheck:
    """Evaluate whether a proposed buy fits the global capital budget."""
    settings = build_capital_budget_settings(config)
    symbol = str(order.get("symbol") or "")
    order_quote, required_quote = calculate_order_budget_requirement(
        config,
        order,
        settings=settings,
    )

    effective_limit, stretch_quote = calculate_effective_capital_limit(
        settings,
        closed_profit,
    )
    committed_quote = (
        max(0.0, float(funds_locked or 0.0))
        + max(0.0, float(open_trade_reserve or 0.0))
        + max(0.0, float(pending_quote or 0.0))
    )
    available_quote = round(effective_limit - committed_quote, 8)

    if not settings.configured:
        return CapitalBudgetCheck(
            ok=True,
            reason="capital_budget_unconfigured",
            symbol=symbol,
            order_quote=order_quote,
            required_quote=required_quote,
            available_quote=available_quote,
            principal_limit=settings.principal_limit,
            effective_limit=effective_limit,
            stretch_quote=stretch_quote,
            funds_locked=funds_locked,
            open_trade_reserve=open_trade_reserve,
            pending_quote=pending_quote,
            projected_total=None,
            buffer_pct=settings.buffer_pct,
            reserve_safety_orders=settings.reserve_safety_orders,
        )

    if settings.principal_limit <= 0:
        return CapitalBudgetCheck(
            ok=False,
            reason="invalid_capital_max_fund",
            symbol=symbol,
            order_quote=order_quote,
            required_quote=required_quote,
            available_quote=available_quote,
            principal_limit=settings.principal_limit,
            effective_limit=effective_limit,
            stretch_quote=stretch_quote,
            funds_locked=funds_locked,
            open_trade_reserve=open_trade_reserve,
            pending_quote=pending_quote,
            projected_total=None,
            buffer_pct=settings.buffer_pct,
            reserve_safety_orders=settings.reserve_safety_orders,
        )

    if required_quote is None:
        return CapitalBudgetCheck(
            ok=False,
            reason="invalid_required_quote",
            symbol=symbol,
            order_quote=order_quote,
            required_quote=None,
            available_quote=available_quote,
            principal_limit=settings.principal_limit,
            effective_limit=effective_limit,
            stretch_quote=stretch_quote,
            funds_locked=funds_locked,
            open_trade_reserve=open_trade_reserve,
            pending_quote=pending_quote,
            projected_total=None,
            buffer_pct=settings.buffer_pct,
            reserve_safety_orders=settings.reserve_safety_orders,
        )

    required_with_buffer = round(required_quote * (1 + settings.buffer_pct), 8)
    projected_total = round(committed_quote + required_with_buffer, 8)
    ok = projected_total <= effective_limit + EPSILON
    return CapitalBudgetCheck(
        ok=ok,
        reason="ok" if ok else "capital_budget_exceeded",
        symbol=symbol,
        order_quote=order_quote,
        required_quote=required_with_buffer,
        available_quote=available_quote,
        principal_limit=settings.principal_limit,
        effective_limit=effective_limit,
        stretch_quote=stretch_quote,
        funds_locked=funds_locked,
        open_trade_reserve=open_trade_reserve,
        pending_quote=pending_quote,
        projected_total=projected_total,
        buffer_pct=settings.buffer_pct,
        reserve_safety_orders=settings.reserve_safety_orders,
    )
