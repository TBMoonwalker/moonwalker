"""Isolated historical comparison using the same pure strategy as live evaluation."""

from dataclasses import asdict
from decimal import Decimal, localcontext
from math import ceil
from threading import BoundedSemaphore
from typing import Any, TypedDict
from uuid import UUID

from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.accumulation_state import AccumulationConflictError
from service.accumulation_strategy import (
    SIZING_POLICY,
    AccumulationCandle,
    AccumulationGuard,
    AccumulationObservations,
    AccumulationParameters,
    accumulation_requested_quote,
    accumulation_signal_reason,
    accumulation_step_severity,
    advance_accumulation_observations,
    calculate_accumulation_market,
)


class ReplayPortfolio(TypedDict):
    cash: Decimal
    units: Decimal
    spent: Decimal
    fees: Decimal
    trades: int
    peak: Decimal
    drawdown: Decimal


def replay_accumulation(
    payload: dict[str, Any], parameters: AccumulationParameters
) -> dict[str, Any]:
    """Compare equal funding; signals execute at the next supplied candle open."""
    if not isinstance(payload, dict) or set(payload) != {
        "candles",
        "funding",
        "fee_bps",
        "slippage_bps",
        "fixed_interval_candles",
    }:
        raise AccumulationStateError(
            "Provide candles, funding, fee_bps, slippage_bps and fixed_interval_candles."
        )
    raw = payload["candles"]
    if (
        not isinstance(raw, list)
        or not parameters.history_length + 2 <= len(raw) <= 20000
    ):
        raise AccumulationStateError(
            "Provide bounded warmup plus at least two evaluation candles (maximum 20000)."
        )
    candles = []
    for row in raw:
        if not isinstance(row, dict) or set(row) != set(
            AccumulationCandle.__dataclass_fields__
        ):
            raise AccumulationStateError(
                "Each candle requires close_ms, open, high, low and close."
            )
        candle = AccumulationCandle(**row)
        if candles and candle.close_ms <= candles[-1].close_ms:
            raise AccumulationStateError(
                "Candles must have unique increasing closing timestamps."
            )
        if parameters.latest_close(candle.close_ms) != candle.close_ms:
            raise AccumulationStateError(
                "Candle timestamps must align with the selected strategy timeframe."
            )
        candles.append(candle)
    funding = Decimal(canonical_decimal(payload["funding"], positive=True))
    fee = Decimal(canonical_decimal(payload["fee_bps"])) / 10000
    slippage = Decimal(canonical_decimal(payload["slippage_bps"])) / 10000
    interval = payload["fixed_interval_candles"]
    if (
        fee > Decimal("0.1")
        or slippage > Decimal("0.1")
        or type(interval) is not int
        or not 1 <= interval <= 20000
    ):
        raise AccumulationStateError(
            "Fee/slippage must be between 0 and 1000 bps; interval must be 1..20000 candles."
        )
    with localcontext() as context:
        context.prec = 50
        start = parameters.history_length
        count = len(candles) - start
        calendar_count = (
            candles[-1].close_ms - candles[start].close_ms
        ) // parameters.interval_ms + 1
        schedule = funding / ceil(calendar_count / interval)
        portfolios: dict[str, ReplayPortfolio] = {
            name: {
                "cash": funding,
                "units": Decimal(0),
                "spent": Decimal(0),
                "fees": Decimal(0),
                "trades": 0,
                "peak": funding,
                "drawdown": Decimal(0),
            }
            for name in ("accumulation", "buy_and_hold", "fixed_interval_dca")
        }
        guard = None
        observations = AccumulationObservations(candles[start - 1].close_ms, 0)
        pending = None
        trades: list[dict[str, Any]] = []
        reasons: dict[str, int] = {}
        gaps = sum(
            current.close_ms - previous.close_ms != parameters.interval_ms
            for previous, current in zip(candles, candles[1:])
        )

        def purchase(
            name: str, budget: Decimal, candle: AccumulationCandle, signal: Any = None
        ) -> None:
            nonlocal guard
            portfolio = portfolios[name]
            budget = min(budget, portfolio["cash"])
            if budget <= 0:
                return
            principal = budget / (1 + fee)
            charge = budget - principal
            units = principal / (Decimal(candle.open) * (1 + slippage))
            portfolio["cash"] -= budget
            portfolio["spent"] += budget
            portfolio["fees"] += charge
            portfolio["units"] += units
            portfolio["trades"] += 1
            if name == "accumulation":
                market = signal
                guard = AccumulationGuard(
                    str(UUID(int=portfolio["trades"])),
                    market.close_ms,
                    market.close,
                    market.atr,
                    1,
                    portfolio["trades"],
                )
                if len(trades) < 100:
                    trades.append(
                        {
                            "signal_close_ms": market.close_ms,
                            "execution_open_ms": candle.close_ms
                            - parameters.interval_ms,
                            "quantity": str(units),
                            "spent": str(budget),
                            "fee": str(charge),
                            "signal_severity": market.severity,
                        }
                    )

        for index in range(start, len(candles)):
            candle = candles[index]
            contiguous = (
                candle.close_ms - candles[index - 1].close_ms == parameters.interval_ms
            )
            if pending is not None and contiguous:
                _, requested = accumulation_requested_quote(
                    accumulation_step_severity(
                        pending.close,
                        pending.previous_close,
                        pending.atr,
                        guard,
                        parameters,
                    ),
                    str(portfolios["accumulation"]["cash"]),
                    parameters,
                )
                purchase("accumulation", Decimal(requested), candle, pending)
            pending = None
            if index == start:
                purchase("buy_and_hold", funding, candle)
            if (
                (candle.close_ms - candles[start].close_ms) // parameters.interval_ms
            ) % interval == 0:
                purchase("fixed_interval_dca", schedule, candle)
            for portfolio in portfolios.values():
                value = portfolio["cash"] + portfolio["units"] * Decimal(candle.close)
                portfolio["peak"] = max(portfolio["peak"], value)
                portfolio["drawdown"] = max(
                    portfolio["drawdown"],
                    (portfolio["peak"] - value) / portfolio["peak"],
                )
            try:
                market = calculate_accumulation_market(
                    candles[index - parameters.history_length + 1 : index + 1],
                    parameters,
                    close_ms=candle.close_ms,
                )
            except AccumulationStateError:
                reasons["WAIT_DATA"] = reasons.get("WAIT_DATA", 0) + 1
                observations = AccumulationObservations(
                    candle.close_ms, guard.consumption_revision if guard else 0
                )
                continue
            observations = advance_accumulation_observations(
                observations, market, guard, parameters
            )
            reason = accumulation_signal_reason(market, observations, guard, parameters)
            reasons[reason] = reasons.get(reason, 0) + 1
            if reason.startswith("BUY_"):
                pending = market
        last = Decimal(candles[-1].close)
        results = []
        for name, portfolio in portfolios.items():
            results.append(
                {
                    "strategy": name,
                    "contributed_quote": str(funding),
                    "units": str(portfolio["units"]),
                    "spent_quote_including_fees": str(portfolio["spent"]),
                    "fees_quote": str(portfolio["fees"]),
                    "cash_quote": str(portfolio["cash"]),
                    "ending_value_quote": str(
                        portfolio["cash"] + portfolio["units"] * last
                    ),
                    "maximum_drawdown_fraction": str(portfolio["drawdown"]),
                    "buy_count": portfolio["trades"],
                }
            )
        return {
            "simulation_only": True,
            "sizing_policy": SIZING_POLICY,
            "parameters": asdict(parameters),
            "funding": str(funding),
            "fee_bps": payload["fee_bps"],
            "slippage_bps": payload["slippage_bps"],
            "warmup_candles": start,
            "evaluation_candles": count,
            "gap_count": gaps,
            "results": results,
            "accumulation_trades": trades,
            "trades_truncated": portfolios["accumulation"]["trades"] > 100,
            "signal_counts": reasons,
            "caveats": [
                "Signals execute at the next candle open with constant adverse slippage and quote-denominated fees; no live orders are submitted.",
                "All strategies receive identical initial funding after warmup. No later deposits or withdrawals are assumed.",
                "Missing intervals cancel pending accumulation buys and require contiguous warmup. Fixed DCA keeps its calendar schedule and skips missing execution bars.",
                "Historical symbol selection can introduce survivorship bias. Results exclude spread variation, liquidity, exchange precision/minimums and future sale fees; they do not predict returns.",
            ],
        }


_REPLAY_SLOT = BoundedSemaphore(1)


def run_accumulation_replay(
    payload: dict[str, Any], parameters: AccumulationParameters
) -> dict[str, Any]:
    """Admit one CPU comparison per instance, including after HTTP cancellation."""
    if not _REPLAY_SLOT.acquire(blocking=False):
        raise AccumulationConflictError(
            "A historical comparison is already running; retry after it finishes."
        )
    try:
        return replay_accumulation(payload, parameters)
    finally:
        _REPLAY_SLOT.release()
