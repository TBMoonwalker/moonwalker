"""Structural guards for the service/orders.py split.

Value: protects=the dca/ package layering (no import of the root facade or
    the engine), the finalization seams living in dca/ (not the facade),
    facade delegation to one shared DcaOrderLifecycle with shared
    collaborator identities, self-wired lifecycle construction parity with
    the facade wiring list, the shared "dca" logger routing, and the D6
    post-construction accumulation seam.
fails_when=any module regrows the split: an import re-couples the layers,
    a seam import returns to the root facade, the facade constructs a second
    lifecycle or divergent collaborators, defaults diverge from the single
    wiring list, a new module logs to the orders logger or a second
    dca.log handler is attached, or the reconciler factory captures the
    accumulation seam at init.
why_new=no existing test asserted the import graph, module shape, wiring
    parity, log routing, or late seam binding.
seam=none (unit-level; the subprocess probe uses the venv interpreter with
    an isolated log directory).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import service.orders as orders_module
from service import order_routing
from service.dca import finalization, order_lifecycle
from service.dca.order_lifecycle import (
    DcaOrderLifecycle,
    DefaultOrderCollaborators,
    build_default_order_collaborators,
)
from service.order_routing import OrderLifecycleRouting
from service.orders import Orders
from service.placement_intents import PlacementAction, PlacementIntentState

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Names that must never appear in the root facade: the trade.buy/trade.sell
# notify and persistence seams live in service/dca/finalization.py.
FORBIDDEN_FACADE_NAMES = (
    "MonitoringService",
    "persist_buy_trade",
    "persist_closed_trade",
    "persist_partial_sell_execution",
    "persist_manual_buy_add",
)


def test_new_modules_do_not_import_facade_or_engine(tmp_path: Path) -> None:
    """Importing the split modules must not pull in service.orders or dca.engine."""
    probe = (
        "import sys\n"
        "import service.dca.finalization\n"
        "import service.dca.order_lifecycle\n"
        "import service.order_routing\n"
        "forbidden = [m for m in ('service.orders', 'service.dca.engine') "
        "if m in sys.modules]\n"
        "print(forbidden)\n"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND_DIR),
        "MOONWALKER_LOG_DIR": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_facade_namespace_has_no_finalization_seams() -> None:
    """The root facade composes; it imports neither notify nor persistence."""
    for name in FORBIDDEN_FACADE_NAMES:
        assert name not in vars(orders_module), name
    source = Path(orders_module.__file__).read_text(encoding="utf-8")
    assert "service.order_persistence" not in source
    assert "from service.monitoring" not in source
    assert "MonitoringService" not in source


def test_facade_composes_single_lifecycle_with_shared_collaborators() -> None:
    """The facade's DcaOrderLifecycle shares the facade's collaborator identity."""
    orders = Orders()

    assert isinstance(orders.dca, DcaOrderLifecycle)
    assert isinstance(orders.routing, OrderLifecycleRouting)
    assert orders.dca.trades is orders.trades
    assert orders.dca.exchange is orders.exchange
    assert orders.dca.monitoring is orders.monitoring
    assert orders.dca.placement_workflow is orders.placement_workflow
    assert orders.dca.placement_intents is orders.placement_intents
    assert orders.dca.capital_budget is orders.capital_budget
    assert orders.dca.delisting_protection is orders.delisting_protection
    assert orders.dca.utils is orders.utils
    assert orders.dca.routing is orders.routing
    assert orders.routing.trades is orders.trades
    assert orders.routing.placement_intents is orders.placement_intents


@pytest.mark.asyncio
async def test_facade_public_methods_delegate_to_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Facade entry points must reach the same lifecycle instance."""
    orders = Orders()
    calls: list[str] = []

    async def record_buy(_order: Any, _config: Any) -> bool:
        calls.append("buy")
        return True

    async def record_sell(_order: Any, _config: Any) -> bool:
        calls.append("sell")
        return True

    async def record_stop(symbol: str, config: Any = None, **_kwargs: Any) -> bool:
        calls.append(f"stop:{symbol}")
        return True

    monkeypatch.setattr(orders.dca, "receive_buy_order", record_buy)
    monkeypatch.setattr(orders.dca, "receive_sell_order", record_sell)
    monkeypatch.setattr(orders.dca, "receive_stop_signal", record_stop)

    assert await orders.receive_buy_order({"symbol": "BTC/USDC"}, {})
    assert await orders.receive_sell_order({"symbol": "BTC/USDC"}, {})
    assert await orders.receive_stop_signal("BTC/USDC")

    assert calls == ["buy", "sell", "stop:BTC/USDC"]


def test_self_wired_lifecycle_builds_same_collaborator_set() -> None:
    """Direct construction resolves the same defaults as the facade wiring list."""
    standalone = DcaOrderLifecycle()
    defaults = build_default_order_collaborators()

    for field in fields(DefaultOrderCollaborators):
        expected_type = type(getattr(defaults, field.name))
        actual = getattr(standalone, field.name)
        assert isinstance(actual, expected_type), field.name
    assert standalone.routing is not None
    assert isinstance(standalone.routing, OrderLifecycleRouting)
    assert standalone.routing.trades is standalone.trades
    assert standalone.routing.placement_intents is standalone.placement_intents
    assert standalone.placement_intents is standalone.placement_workflow.intents


def test_new_modules_route_logs_to_shared_dca_logger() -> None:
    """Both new dca/ modules log through the engine's shared "dca" logger."""
    import logging

    dca_logger = logging.getLogger("dca")
    orders_logger = logging.getLogger("orders")

    assert finalization.logging is dca_logger
    assert order_lifecycle.logging is dca_logger
    assert order_routing.logging is orders_logger
    assert orders_logger is not dca_logger
    # The "dca" logger must be the only owner of dca.log: a distinct logger
    # name would attach a second handler and split rotation/retention (OV3).
    other_owners = [
        name
        for name, candidate in logging.Logger.manager.loggerDict.items()
        if isinstance(candidate, logging.Logger)
        and candidate is not dca_logger
        and any(
            isinstance(handler, logging.FileHandler)
            and Path(getattr(handler, "baseFilename", "")).name == "dca.log"
            for handler in candidate.handlers
        )
    ]
    assert other_owners == []
    # The shared "dca" logger must own exactly one handler that writes to
    # dca.log; a second one double-writes records and splits rotation/retention.
    # Count dca.log handlers specifically: the logger may also carry unrelated
    # test-session handlers (e.g. a /dev/null silencer) that do not touch it.
    dca_log_handlers = [
        handler
        for handler in dca_logger.handlers
        if isinstance(handler, logging.FileHandler)
        and Path(getattr(handler, "baseFilename", "")).name == "dca.log"
    ]
    assert len(dca_log_handlers) == 1


@pytest.mark.asyncio
async def test_bybit_reconciler_reads_accumulation_seam_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D6: app.py binds accumulation_recovery after Orders() construction.

    The bybit recovery branch builds the reconciler through the facade's
    factory at call time, so a seam assigned post-construction must be
    observed; a capture-at-init bug would silently route accumulation
    intents to the classic path.
    """
    orders = Orders()
    sentinel = object()
    captured: list[Any] = []

    class _CaptureReconciler:
        def __init__(
            self,
            exchange: Any,
            resume: Any,
            intents: Any,
            *,
            accumulation_recovery: Any = None,
        ) -> None:
            captured.append(accumulation_recovery)

        async def reconcile_operation(self, _operation_id: str, _config: Any) -> str:
            return "rejected"

    monkeypatch.setattr(orders_module, "PlacementReconciler", _CaptureReconciler)
    pending = SimpleNamespace(
        operation_id="buy-late-seam",
        exchange_name="bybit",
        symbol="DOGE/USDC",
        action=PlacementAction.BUY.value,
        state=PlacementIntentState.ACCEPTED.value,
    )

    async def fake_list_nonterminal() -> list[Any]:
        return [pending]

    monkeypatch.setattr(
        orders.dca.placement_intents,
        "list_nonterminal",
        fake_list_nonterminal,
    )

    # Pre-assignment build: the seam is still unbound.
    orders._build_placement_reconciler()
    orders.accumulation_recovery = sentinel
    filled, precheck = await orders.dca._execute_budgeted_buy_order(
        {"symbol": "DOGE/USDC", "ordersize": 5},
        {"exchange": "bybit", "dry_run": True},
    )

    assert filled is False
    assert precheck is not None
    assert precheck["reason"] == "placement_rejected"
    assert captured == [None, sentinel]
