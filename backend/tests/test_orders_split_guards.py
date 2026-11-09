"""Structural guards for the service/orders.py split and facade removal.

Value: protects=the dca/ package layering (no import of the engine),
    self-wired DcaOrderLifecycle construction parity with the shared
    wiring list, and the shared "dca" logger routing.
fails_when=any module regrows the split: an import re-couples the
    layers, defaults diverge from the single wiring list, or a new
    module attaches a second dca.log handler.
why_new=no existing test asserted the import graph, wiring parity, or
    log routing. The facade-specific guards moved with their owners when
    service/orders.py was removed: the composition identity guard and
    the D6 late-seam guard now live in
    test_placement_recovery_entry.py against the entry.
seam=none (unit-level; the subprocess probe uses the venv interpreter
    with an isolated log directory).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

from service import order_routing
from service.dca import finalization, order_lifecycle
from service.dca.order_lifecycle import (
    DcaOrderLifecycle,
    DefaultOrderCollaborators,
    build_default_order_collaborators,
)
from service.order_routing import OrderLifecycleRouting

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_new_modules_do_not_import_engine(tmp_path: Path) -> None:
    """Importing the split modules must not pull in dca.engine."""
    probe = (
        "import sys\n"
        "import service.dca.finalization\n"
        "import service.dca.order_lifecycle\n"
        "import service.order_routing\n"
        "forbidden = [m for m in ('service.dca.engine',) "
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


def test_self_wired_lifecycle_builds_same_collaborator_set() -> None:
    """Direct construction resolves the same defaults as the wiring list."""
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
