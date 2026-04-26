"""Global capital-budget authority for buy admission and execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

import helper
import model
from service.capital_budget_logic import (
    CapitalBudgetCheck,
    build_capital_budget_settings,
    calculate_effective_capital_limit,
    estimate_open_trade_reserve,
    evaluate_capital_budget,
    has_capital_budget_config,
    resolve_capital_max_fund,
)
from tortoise.exceptions import BaseORMException
from tortoise.functions import Sum

logging = helper.LoggerFactory.get_logger("logs/capital_budget.log", "capital_budget")


@dataclass(frozen=True)
class CapitalBudgetUsage:
    """DB-backed capital usage snapshot."""

    funds_locked: float
    open_trade_reserve: float
    closed_profit: float
    unavailable_reason: str | None = None


class CapitalBudgetLease:
    """Process-local reservation for an in-flight buy attempt."""

    def __init__(
        self,
        service: "CapitalBudgetService",
        lease_id: str | None,
    ) -> None:
        self._service = service
        self._lease_id = lease_id
        self._released = False

    async def release(self) -> None:
        """Release this reservation once the buy is finalized or abandoned."""
        if self._released or self._lease_id is None:
            return
        self._released = True
        await self._service.release_lease(self._lease_id)

    async def __aenter__(self) -> "CapitalBudgetLease":
        """Return the lease for async-context use."""
        return self

    async def __aexit__(self, *_args: object) -> None:
        """Release reservations when leaving the async context."""
        await self.release()


class CapitalBudgetService:
    """Enforce the single-node hard capital budget for buy paths."""

    _lock = asyncio.Lock()
    _leases: dict[str, float] = {}

    async def get_runtime_state(self, config: dict) -> dict[str, float | bool | str]:
        """Return capital-budget telemetry for dashboard/statistics payloads."""
        if not has_capital_budget_config(config):
            return {
                "capital_budget_available": True,
                "capital_budget_reason": "capital_budget_unconfigured",
                "capital_max_fund": 0.0,
                "capital_effective_max_fund": 0.0,
                "capital_stretch_quote": 0.0,
                "capital_funds_locked": 0.0,
                "capital_open_trade_reserve": 0.0,
                "capital_pending_quote": self._pending_reserved_quote(),
                "capital_available_quote": 0.0,
            }
        usage = await self._load_usage(config)
        pending_quote = self._pending_reserved_quote()
        if usage.unavailable_reason is not None:
            return {
                "capital_budget_available": False,
                "capital_budget_reason": usage.unavailable_reason,
                "capital_max_fund": resolve_capital_max_fund(config),
                "capital_effective_max_fund": resolve_capital_max_fund(config),
                "capital_stretch_quote": 0.0,
                "capital_funds_locked": 0.0,
                "capital_open_trade_reserve": 0.0,
                "capital_pending_quote": pending_quote,
                "capital_available_quote": 0.0,
            }

        settings = build_capital_budget_settings(config)
        effective_limit, stretch_quote = calculate_effective_capital_limit(
            settings,
            usage.closed_profit,
        )
        committed = usage.funds_locked + usage.open_trade_reserve + pending_quote
        return {
            "capital_budget_available": bool(
                (not settings.configured)
                or (settings.principal_limit > 0 and committed <= effective_limit)
            ),
            "capital_budget_reason": (
                "capital_budget_unconfigured"
                if not settings.configured
                else (
                    "invalid_capital_max_fund"
                    if settings.principal_limit <= 0
                    else (
                        "capital_budget_exceeded"
                        if committed > effective_limit
                        else "ok"
                    )
                )
            ),
            "capital_max_fund": settings.principal_limit,
            "capital_effective_max_fund": effective_limit,
            "capital_stretch_quote": stretch_quote,
            "capital_funds_locked": round(usage.funds_locked, 8),
            "capital_open_trade_reserve": round(usage.open_trade_reserve, 8),
            "capital_pending_quote": round(pending_quote, 8),
            "capital_available_quote": round(effective_limit - committed, 8),
        }

    async def check_order(
        self,
        order: dict,
        config: dict,
        *,
        include_pending: bool = True,
    ) -> CapitalBudgetCheck:
        """Check a buy order without creating a lease."""
        if not has_capital_budget_config(config):
            return evaluate_capital_budget(
                config,
                order,
                funds_locked=0.0,
                open_trade_reserve=0.0,
                pending_quote=0.0,
                closed_profit=0.0,
            )
        usage = await self._load_usage(config)
        pending_quote = self._pending_reserved_quote() if include_pending else 0.0
        if usage.unavailable_reason is not None:
            return self._unavailable_check(
                order,
                config,
                usage=usage,
                pending_quote=pending_quote,
            )
        return evaluate_capital_budget(
            config,
            order,
            funds_locked=usage.funds_locked,
            open_trade_reserve=usage.open_trade_reserve,
            pending_quote=pending_quote,
            closed_profit=usage.closed_profit,
        )

    async def acquire_order_lease(
        self,
        order: dict,
        config: dict,
    ) -> tuple[CapitalBudgetLease, CapitalBudgetCheck]:
        """Atomically check and reserve capital for one in-flight buy."""
        if not has_capital_budget_config(config):
            check = evaluate_capital_budget(
                config,
                order,
                funds_locked=0.0,
                open_trade_reserve=0.0,
                pending_quote=0.0,
                closed_profit=0.0,
            )
            return CapitalBudgetLease(self, None), check
        async with self._lock:
            usage = await self._load_usage(config)
            pending_quote = self._pending_reserved_quote()
            if usage.unavailable_reason is not None:
                check = self._unavailable_check(
                    order,
                    config,
                    usage=usage,
                    pending_quote=pending_quote,
                )
                return CapitalBudgetLease(self, None), check

            check = evaluate_capital_budget(
                config,
                order,
                funds_locked=usage.funds_locked,
                open_trade_reserve=usage.open_trade_reserve,
                pending_quote=pending_quote,
                closed_profit=usage.closed_profit,
            )
            if not check.ok:
                return CapitalBudgetLease(self, None), check

            lease_amount = max(0.0, float(check.required_quote or 0.0))
            if lease_amount <= 0:
                return CapitalBudgetLease(self, None), check

            lease_id = uuid4().hex
            self._leases[lease_id] = lease_amount
            return CapitalBudgetLease(self, lease_id), check

    async def release_lease(self, lease_id: str) -> None:
        """Release a pending capital reservation."""
        async with self._lock:
            self._leases.pop(lease_id, None)

    @classmethod
    def _pending_reserved_quote(cls) -> float:
        """Return total process-local pending buy reservations."""
        return round(sum(float(value or 0.0) for value in cls._leases.values()), 8)

    async def _load_usage(self, config: dict) -> CapitalBudgetUsage:
        """Load a fresh DB-backed capital usage snapshot."""
        try:
            open_trades = await model.OpenTrades.all().values(
                "symbol",
                "so_count",
                "cost",
                "unsellable_amount",
                "unsellable_reason",
            )
            symbols = [
                str(row.get("symbol") or "")
                for row in open_trades
                if str(row.get("symbol") or "")
            ]
            trades_by_symbol = {symbol: 0.0 for symbol in symbols}
            if symbols:
                trade_rows = await model.Trades.filter(symbol__in=symbols).values(
                    "symbol",
                    "ordersize",
                )
                for row in trade_rows:
                    symbol = str(row.get("symbol") or "")
                    trades_by_symbol[symbol] = trades_by_symbol.get(symbol, 0.0) + (
                        float(row.get("ordersize") or 0.0)
                    )

            funds_locked = 0.0
            for row in open_trades:
                symbol = str(row.get("symbol") or "")
                open_cost = float(row.get("cost") or 0.0)
                trade_cost = trades_by_symbol.get(symbol, 0.0)
                funds_locked += open_cost if open_cost > 0 else trade_cost

            closed_profit_rows = (
                await model.ClosedTrades.all()
                .annotate(total=Sum("profit"))
                .values_list("total", flat=True)
            )
            closed_profit = float(
                (closed_profit_rows[0] if closed_profit_rows else 0.0) or 0.0
            )
            return CapitalBudgetUsage(
                funds_locked=round(funds_locked, 8),
                open_trade_reserve=estimate_open_trade_reserve(config, open_trades),
                closed_profit=round(closed_profit, 8),
            )
        except BaseORMException as exc:
            logging.error(
                "Capital budget usage snapshot unavailable: %s",
                exc,
                exc_info=True,
            )
            return CapitalBudgetUsage(
                funds_locked=0.0,
                open_trade_reserve=0.0,
                closed_profit=0.0,
                unavailable_reason="capital_budget_unavailable",
            )

    @staticmethod
    def _unavailable_check(
        order: dict,
        config: dict,
        *,
        usage: CapitalBudgetUsage,
        pending_quote: float,
    ) -> CapitalBudgetCheck:
        """Build a fail-closed result when budget usage cannot be loaded."""
        settings = build_capital_budget_settings(config)
        principal_limit = resolve_capital_max_fund(config)
        return CapitalBudgetCheck(
            ok=False,
            reason=usage.unavailable_reason or "capital_budget_unavailable",
            symbol=str(order.get("symbol") or ""),
            order_quote=None,
            required_quote=None,
            available_quote=None,
            principal_limit=principal_limit,
            effective_limit=principal_limit,
            stretch_quote=0.0,
            funds_locked=usage.funds_locked,
            open_trade_reserve=usage.open_trade_reserve,
            pending_quote=pending_quote,
            projected_total=None,
            buffer_pct=0.0,
            reserve_safety_orders=settings.reserve_safety_orders,
        )
