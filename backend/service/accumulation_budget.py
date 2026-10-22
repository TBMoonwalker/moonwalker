"""Fresh account evidence and shared capital headroom for accumulation admission.

A trusted adapter captures a ledger token BEFORE reading the exchange balance.
Admission compares it again under the shared capital lock and DB transaction.
No network I/O belongs in these functions. Unknown evidence never means unlimited
funds, including when the optional configured capital cap is absent.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import ROUND_DOWN, ROUND_UP, Decimal, localcontext
from typing import Any

import model
from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.capital_budget import (
    CapitalBudgetService,
    CapitalBudgetUsage,
    load_pending_capital,
)
from service.capital_budget_logic import (
    build_capital_budget_settings,
    calculate_effective_capital_limit,
)
from tortoise.transactions import in_transaction

QUOTE_QUANTUM = Decimal("0.00000001")


@dataclass(frozen=True)
class AccumulationFundingSnapshot:
    """Trusted, coherent balance evidence, never a dashboard-supplied payload.

    reflected_holds maps operation IDs to quote still held by the exchange and
    already excluded from free_quote. Spent fills must already be reflected in
    free_quote. The adapter must reconcile exchange orders before producing this
    evidence; timestamps alone cannot prove a cached exchange balance coherent.
    """

    account_scope: str
    exchange_name: str
    quote_currency: str
    free_quote: str
    observed_at_ms: int
    ledger_token: str
    reflected_holds: tuple[tuple[str, str], ...] = ()


async def _budget_state(
    config: dict[str, Any],
) -> tuple[str, CapitalBudgetUsage, dict[str, Decimal]]:
    usage = await CapitalBudgetService()._load_usage(config)
    pending = await load_pending_capital()
    # Include lifecycle changes even if their monetary aggregate is unchanged.
    holdings = (
        await model.OpenTrades.all()
        .order_by("id")
        .values(
            "id",
            "symbol",
            "amount",
            "cost",
            "accumulation_net_quantity",
            "accumulation_remaining_cost",
            "accumulation_fees_json",
        )
    )
    placements = (
        await model.PlacementIntent.all()
        .exclude(state__in=["completed", "rejected"])
        .order_by("id")
        .values("operation_id", "state", "updated_at")
    )
    payload = json.dumps(
        [
            config,
            asdict(usage),
            pending,
            holdings,
            placements,
            sorted(CapitalBudgetService._leases.items()),
        ],
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest(), usage, pending


async def capture_accumulation_funding_token(config: dict[str, Any]) -> str:
    """Capture a coherent ledger identity before fetching fresh account evidence."""
    async with CapitalBudgetService._lock:
        async with in_transaction():
            token, _, _ = await _budget_state(config)
            return token


def required_accumulation_quote(principal: str, config: dict[str, Any]) -> Decimal:
    """Apply the existing execution buffer, conservatively rounded to eight places."""
    with localcontext() as context:
        context.prec = 80
        buffer = Decimal(str(build_capital_budget_settings(config).buffer_pct))
        if not buffer.is_finite() or buffer < 0:
            raise AccumulationStateError("Invalid execution buffer.")
        return (Decimal(canonical_decimal(principal)) * (1 + buffer)).quantize(
            QUOTE_QUANTUM, rounding=ROUND_UP
        )


async def usable_accumulation_quote(
    config: dict[str, Any],
    snapshot: AccumulationFundingSnapshot,
    *,
    now_ms: int,
    exclude_operation_id: str | None = None,
) -> str | None:
    """Return principal headroom while the caller holds the shared capital lock.

    The caller also owns a DB transaction so holdings, journal and checkpoints
    cannot be mixed across fill transitions. No additional strategy reserve is
    introduced. Exchange-reflected holds are deducted exactly once.
    """
    if (
        type(snapshot.observed_at_ms) is not int
        or not 0 <= now_ms - snapshot.observed_at_ms <= 10000
    ):
        return None
    token, usage, pending = await _budget_state(config)
    if token != snapshot.ledger_token or usage.unavailable_reason:
        return None
    if exclude_operation_id is not None:
        # Only the execution owner may reclaim its own already-reserved amount.
        # A fresh immutable snapshot still has to match the complete ledger.
        if exclude_operation_id not in pending:
            return None
        pending.pop(exclude_operation_id)
    with localcontext() as context:
        context.prec = 80
        free = Decimal(canonical_decimal(snapshot.free_quote))
        reflected = dict(snapshot.reflected_holds)
        if (
            len(reflected) != len(snapshot.reflected_holds)
            or set(reflected) - pending.keys()
        ):
            return None
        exchange_pending = Decimal(0)
        for operation_id, amount in pending.items():
            hold = Decimal(canonical_decimal(reflected.get(operation_id, "0")))
            if hold > amount:
                return None
            exchange_pending += amount - hold
        active_ids = CapitalBudgetService._active_operation_ids()
        local = sum(
            (Decimal(str(value[0])) for value in CapitalBudgetService._leases.values()),
            Decimal(0),
        )
        # Bound leases replace their durable records, rather than counting both.
        unbound = sum(
            (
                Decimal(str(value[0]))
                for value in CapitalBudgetService._leases.values()
                if value[1] not in pending
            ),
            Decimal(0),
        )
        exchange_available = max(Decimal(0), free - exchange_pending - unbound)
        settings = build_capital_budget_settings(config)
        available = exchange_available
        if settings.configured:
            if settings.principal_limit <= 0:
                return None
            limit, _ = calculate_effective_capital_limit(settings, usage.closed_profit)
            committed = (
                Decimal(usage.funds_locked_exact or str(usage.funds_locked))
                + Decimal(str(usage.open_trade_reserve))
                + local
                + sum(
                    (value for key, value in pending.items() if key not in active_ids),
                    Decimal(0),
                )
            )
            available = min(available, max(Decimal(0), Decimal(str(limit)) - committed))
        multiplier = required_accumulation_quote("1", config)
        return str(
            (available / multiplier).quantize(QUOTE_QUANTUM, rounding=ROUND_DOWN)
        )
