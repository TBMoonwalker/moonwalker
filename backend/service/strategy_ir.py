"""Pure validation for Strategy Builder intermediate representations."""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import Any


def validate_strategy_ir_document(
    ir: dict[str, Any],
    *,
    schema_version: int,
    palette_types: Collection[str],
    supported_indicators: Collection[str],
    checked_at_factory: Callable[[], str],
) -> dict[str, Any]:
    """Validate one strategy IR without persistence or runtime dependencies."""
    blocking: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not isinstance(ir, dict):
        blocking.append(
            {"group": "Schema", "message": "Strategy IR must be an object."}
        )
        return _validation_payload(blocking, warnings, 0, (), checked_at_factory)

    document_schema_version = ir.get("schema_version")
    if document_schema_version != schema_version:
        blocking.append(
            {
                "group": "Schema",
                "message": (f"Unsupported schema version {document_schema_version!r}."),
            }
        )

    nodes = ir.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        blocking.append(
            {"group": "Graph", "message": "Add at least one executable node."}
        )
        return _validation_payload(blocking, warnings, 0, (), checked_at_factory)

    node_by_id: dict[str, dict[str, Any]] = {}
    required_methods: set[str] = set()
    min_history_candles = 0
    data_node_types = {
        "constant_value",
        "close_price",
        "low_price",
        "high_price",
        "indicator",
    }
    for raw_node in nodes:
        if not isinstance(raw_node, dict):
            blocking.append(
                {"group": "Graph", "message": "Each node must be an object."}
            )
            continue
        node_id = str(raw_node.get("id") or "").strip()
        node_type = str(raw_node.get("type") or "").strip()
        if not node_id:
            blocking.append({"group": "Graph", "message": "Every node needs an id."})
            continue
        if node_id in node_by_id:
            blocking.append(
                {"group": "Graph", "message": f"Duplicate node id '{node_id}'."}
            )
        node_by_id[node_id] = raw_node
        if node_type not in palette_types:
            blocking.append(
                {
                    "group": "Graph",
                    "message": f"Node '{node_id}' uses unsupported type '{node_type}'.",
                }
            )
        node_methods, node_history = node_runtime_requirements(raw_node)
        required_methods.update(node_methods)
        min_history_candles = max(min_history_candles, node_history)

    root = str(ir.get("root") or "").strip()
    if not root or root not in node_by_id:
        blocking.append({"group": "Graph", "message": "Select a valid decision node."})
    elif str(node_by_id[root].get("type") or "") in data_node_types:
        blocking.append(
            {
                "group": "Graph",
                "message": "The decision node must be logic, state, or condition.",
            }
        )

    input_count_by_target, input_ports_by_target = _index_connections(
        ir.get("connections"),
        node_by_id,
        blocking,
    )
    for node_id, node in node_by_id.items():
        node_type = str(node.get("type") or "")
        if node_type in {"all", "any"} and input_count_by_target.get(node_id, 0) == 0:
            blocking.append(
                {
                    "group": "Graph",
                    "message": f"Logic node '{node_id}' needs at least one input.",
                }
            )
        if node_type == "comparison":
            _validate_comparison_node(
                node_id,
                input_count_by_target,
                input_ports_by_target,
                blocking,
            )
        if node_type == "indicator":
            _validate_indicator_node(
                node_id,
                node,
                supported_indicators,
                blocking,
            )
        if node_type == "swing_low_state" and input_count_by_target.get(node_id, 0) < 2:
            blocking.append(
                {
                    "group": "Graph",
                    "message": (
                        f"Swing-low state node '{node_id}' needs the previous "
                        "and two-back close price inputs."
                    ),
                }
            )

    if not required_methods:
        warnings.append(
            {
                "group": "Readiness",
                "message": "No indicator calls are required by this graph.",
            }
        )

    return _validation_payload(
        blocking,
        warnings,
        min_history_candles,
        tuple(sorted(required_methods)),
        checked_at_factory,
    )


def _index_connections(
    connections: Any,
    node_by_id: dict[str, dict[str, Any]],
    blocking: list[dict[str, str]],
) -> tuple[dict[str, int], dict[str, set[str]]]:
    """Validate and index graph connections by their target node."""
    input_count_by_target: dict[str, int] = {}
    input_ports_by_target: dict[str, set[str]] = {}
    if not isinstance(connections, list):
        return input_count_by_target, input_ports_by_target

    for raw_connection in connections:
        if not isinstance(raw_connection, dict):
            blocking.append(
                {"group": "Graph", "message": "Each connection must be an object."}
            )
            continue
        source = str(raw_connection.get("source") or "").strip()
        target = str(raw_connection.get("target") or "").strip()
        if source not in node_by_id or target not in node_by_id:
            blocking.append(
                {
                    "group": "Graph",
                    "message": "Connections must reference existing nodes.",
                }
            )
            continue
        input_count_by_target[target] = input_count_by_target.get(target, 0) + 1
        target_input = str(
            raw_connection.get("target_input")
            or raw_connection.get("targetInput")
            or raw_connection.get("input")
            or ""
        ).strip()
        if target_input:
            input_ports_by_target.setdefault(target, set()).add(
                normalize_comparison_port(target_input)
            )
    return input_count_by_target, input_ports_by_target


def _validate_comparison_node(
    node_id: str,
    input_count_by_target: dict[str, int],
    input_ports_by_target: dict[str, set[str]],
    blocking: list[dict[str, str]],
) -> None:
    """Validate comparison nodes have two graphical inputs."""
    if input_count_by_target.get(node_id, 0) < 2:
        blocking.append(
            {
                "group": "Graph",
                "message": f"Comparison node '{node_id}' needs value1 and value2 inputs.",
            }
        )
        return
    ports = input_ports_by_target.get(node_id, set())
    if not {"value1", "value2"}.issubset(ports):
        blocking.append(
            {
                "group": "Graph",
                "message": (
                    f"Comparison node '{node_id}' needs explicit value1 and value2 "
                    "connection ports."
                ),
            }
        )


def _validate_indicator_node(
    node_id: str,
    node: dict[str, Any],
    supported_indicators: Collection[str],
    blocking: list[dict[str, str]],
) -> None:
    """Validate generic indicator nodes only reference supported indicators."""
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    indicator = str(params.get("indicator") or "").strip()
    if indicator not in supported_indicators:
        blocking.append(
            {
                "group": "Indicators",
                "message": (
                    f"Indicator node '{node_id}' uses unsupported indicator "
                    f"'{indicator or 'empty'}'."
                ),
            }
        )


def normalize_comparison_port(port: str) -> str:
    """Return the canonical comparison port name for current and legacy graphs."""
    if port == "left":
        return "value1"
    if port == "right":
        return "value2"
    return port


def _validation_payload(
    blocking: list[dict[str, str]],
    warnings: list[dict[str, str]],
    min_history_candles: int,
    required_methods: tuple[str, ...],
    checked_at_factory: Callable[[], str],
) -> dict[str, Any]:
    """Return the API validation payload shape."""
    return {
        "status": "invalid" if blocking else "valid",
        "blocking_errors": blocking,
        "warnings": warnings,
        "required_history": {
            "candles": min_history_candles,
            "label": (
                f"{min_history_candles} closed candles"
                if min_history_candles
                else "No extra history required"
            ),
        },
        "hook_readiness": [
            {
                "name": method,
                "ready": True,
                "message": "Indicator hook available.",
            }
            for method in required_methods
        ],
        "checked_at": checked_at_factory(),
    }


def node_runtime_requirements(
    node: dict[str, Any],
) -> tuple[tuple[str, ...], int]:
    """Return indicator methods and history required by a node."""
    node_type = str(node.get("type") or "")
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    if node_type == "indicator":
        indicator = str(params.get("indicator") or "")
        if indicator == "ema":
            length = int(params.get("length") or 20)
            return (("calculate_ema", "get_close_price"), max(length + 2, 200))
        if indicator == "rsi":
            length = int(params.get("length") or 14)
            return (("calculate_rsi_series",), max(length + 2, 50))
        if indicator.startswith("bollinger_"):
            length = int(params.get("length") or 20)
            return (("calculate_bollinger_bands_series",), max(length + 2, 50))
        if indicator.startswith("macd_"):
            slow_period = int(params.get("slow_period") or 26)
            signal_period = int(params.get("signal_period") or 9)
            return (
                ("calculate_macd_series",),
                max(slow_period + signal_period + 2, 50),
            )
        return ((), 0)
    if node_type == "constant_value":
        return ((), 0)
    if node_type == "close_price":
        return (("get_close_price",), int(params.get("lookback") or 50))
    if node_type == "low_price":
        return (("get_low_price",), int(params.get("lookback") or 50))
    if node_type == "high_price":
        return (("get_high_price",), int(params.get("lookback") or 50))
    if node_type in {"fresh_signal_state", "swing_low_state"}:
        return (("calculate_ema", "get_close_price"), 200)
    return ((), 0)
