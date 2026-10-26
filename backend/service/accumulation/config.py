"""Configuration boundaries for accumulation drafts and initial entry selection."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import model
from service.accumulation.contracts import AccumulationStateError, canonical_decimal
from service.config_runtime_store import ConfigUpdateAction
from service.lifecycle_routing import has_pending_accumulation_work
from service.order_requests import normalize_order_symbol
from service.strategy_runtime import load_accumulation_strategy_version
from service.trading_maintenance import trading_maintenance_barrier
from tortoise.exceptions import ConfigurationError, OperationalError


async def configuration_mode_guard(current: Mapping[str, Any]) -> dict[str, Any]:
    """Explain entry-mode switching constraints without exchange access."""
    try:
        open_count = await model.OpenTrades.all().count()
        active_count = await model.AccumulationActivation.exclude(
            state="stopped"
        ).count()
        unsettled = (
            await model.PlacementIntent.exclude(
                state__in=("completed", "rejected")
            ).exists()
            or await has_pending_accumulation_work()
        )
        live_running = (
            current.get("dry_run", True) is False
            and current.get("trading_paused") is not True
        )
        blocked = bool(open_count or active_count or unsettled or live_running)
        actions = []
        if open_count:
            noun = "holding" if open_count == 1 else "holdings"
            actions.append(f"close {open_count} open {noun}")
        if active_count:
            noun = "registration" if active_count == 1 else "registrations"
            actions.append(f"stop {active_count} active accumulation {noun}")
        if unsettled:
            actions.append("reconcile unresolved orders")
        if live_running:
            actions.append("pause live trading")
        message = (
            "Before changing trade mode: " + "; ".join(actions) + "."
            if actions
            else None
        )
    except (ConfigurationError, OperationalError):
        open_count, active_count, blocked = 0, 0, True
        message = "Trading state could not be verified; refresh before changing mode."
    return {
        "blocked": blocked,
        "can_switch": not blocked,
        "current_trade_mode": current.get("trade_mode", "dynamic_dca"),
        "open_trade_count": open_count,
        "active_registration_count": active_count,
        "message": message,
    }


ENTRY_KEYS = frozenset(
    {
        "trade_mode",
        "timeframe",
        "accumulation_strategy_version_id",
        "dca",
        "bo",
        "signal",
        "signal_settings",
        "symbol_list",
        "market",
        "currency",
        "dry_run",
        "max_bots",
        "capital_max_fund",
        "exchange",
        "key",
        "secret",
        "exchange_hostname",
        "sandbox",
        "autopilot",
    }
)


def accumulation_available() -> bool:
    """Read a source-owned capability; editable config cannot enable the feature."""
    from service.accumulation.runtime import ACCUMULATION_RUNTIME_AVAILABLE

    return ACCUMULATION_RUNTIME_AVAILABLE


@asynccontextmanager
async def configuration_mode_boundary(
    current: Mapping[str, Any], updates: Mapping[str, Any]
) -> AsyncIterator[bool]:
    """Drain execution before the config write lock to avoid worker/config deadlocks."""
    raw = updates.get("trade_mode")
    candidate = (
        raw.get("value")
        if isinstance(raw, dict)
        else current.get("trade_mode", "dynamic_dca")
    )
    changed = (candidate or "dynamic_dca") != current.get("trade_mode", "dynamic_dca")
    async with AsyncExitStack() as stack:
        if changed:
            try:
                await stack.enter_async_context(
                    trading_maintenance_barrier.maintenance()
                )
            except RuntimeError as exc:
                raise AccumulationStateError(
                    "Trading maintenance is active; refresh before changing mode."
                ) from exc
        yield changed


async def validate_accumulation_configuration(
    current: Mapping[str, Any],
    actions: list[ConfigUpdateAction],
    *,
    mode_change_admitted: bool,
) -> None:
    """Validate the full proposed selection under Config's shared write lock."""
    changed_keys = {action.key for action in actions}
    if not changed_keys & ENTRY_KEYS:
        return
    proposed = dict(current)
    for action in actions:
        proposed[action.key] = action.runtime_value if action.persist else None
    mode = proposed.get("trade_mode") or "dynamic_dca"
    if mode not in {"dynamic_dca", "accumulation"}:
        raise AccumulationStateError(
            "Unknown trade mode; select Dynamic DCA or Accumulation."
        )
    if mode == "accumulation" and "timeframe" in changed_keys:
        active_pins = await model.AccumulationActivation.exclude(
            state="stopped"
        ).values_list("strategy_version_id", flat=True)
        for active_pin in set(active_pins):
            await load_accumulation_strategy_version(
                active_pin, timeframe=proposed.get("timeframe")
            )
    pin = proposed.get("accumulation_strategy_version_id")
    if mode == "accumulation" or (
        "accumulation_strategy_version_id" in changed_keys
        and pin is not None
        and pin != current.get("accumulation_strategy_version_id")
    ):
        if not accumulation_available():
            raise AccumulationStateError("Accumulation is unavailable in this release.")
        if pin is not None:
            await load_accumulation_strategy_version(
                pin, timeframe=proposed.get("timeframe")
            )
    if mode != current.get("trade_mode", "dynamic_dca"):
        if not mode_change_admitted:
            raise AccumulationStateError(
                "Trade mode changed concurrently; refresh and retry."
            )
        if (
            current.get("dry_run", True) is False
            and current.get("trading_paused") is not True
        ):
            raise AccumulationStateError(
                "Pause Moonwalker before changing the live entry mode."
            )
        if (
            await model.OpenTrades.all().exists()
            or await model.AccumulationActivation.exclude(state="stopped").exists()
            or await model.PlacementIntent.exclude(
                state__in=("completed", "rejected")
            ).exists()
            or await has_pending_accumulation_work()
        ):
            raise AccumulationStateError(
                "Finish existing holdings, registrations and unresolved orders before changing entry mode."
            )
    if mode != "accumulation":
        return
    if proposed.get("dca") is not True:
        raise AccumulationStateError("Enable trade mode management for accumulation.")
    if proposed.get("signal") not in {"asap", "csv_signal"}:
        raise AccumulationStateError(
            "Accumulation supports only ASAP fixed symbols or CSV inventory."
        )
    if proposed.get("market") != "spot":
        raise AccumulationStateError("Accumulation requires spot markets.")
    if proposed.get("autopilot") is True:
        raise AccumulationStateError("Disable Autopilot before selecting accumulation.")
    currency = str(proposed.get("currency") or "").strip().upper()
    if proposed.get("signal") == "asap":
        amount = proposed.get("bo")
        if amount is not None or proposed.get("dry_run", True) is not True:
            try:
                canonical_decimal(str(amount), positive=True)
            except AccumulationStateError as exc:
                raise AccumulationStateError(
                    "Set a positive base order amount for ASAP."
                ) from exc
        symbols = proposed.get("symbol_list")
        if (
            not isinstance(symbols, str)
            or not symbols.strip()
            or "http" in symbols.lower()
        ):
            raise AccumulationStateError(
                "Accumulation ASAP requires a fixed symbol list."
            )
        for value in symbols.split(","):
            symbol = normalize_order_symbol(value)
            if symbol.split("/")[1] != currency or ":" in symbol:
                raise AccumulationStateError(
                    "Accumulation symbols must use the configured spot quote."
                )
    if pin is None and proposed.get("dry_run", True) is not True:
        raise AccumulationStateError(
            "Select an exact compatible accumulation strategy version before live entry."
        )
