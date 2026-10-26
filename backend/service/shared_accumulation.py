"""Shared builder representations for accumulation presets, without migrations."""

from dataclasses import asdict
from typing import Any

from service.accumulation_strategy import parse_accumulation_strategy_document


def legacy_accumulation_graph(
    document: dict[str, Any], slug: str, name: str, builtin: bool
) -> dict[str, Any]:
    """Present a legacy immutable preset in the common editor; leave its row intact."""
    parameters = parse_accumulation_strategy_document(document)
    return {
        "schema_version": 1,
        "slug": slug,
        "name": name,
        "description": "ATR dip execution with manual accumulation exits. Add shared buy conditions here.",
        "kind": "builtin" if builtin else "custom",
        "root": "eligible",
        "accumulation": asdict(parameters),
        "nodes": [
            {
                "id": "enabled",
                "type": "constant_value",
                "label": "Enabled",
                "params": {"value": 1},
            },
            {
                "id": "one",
                "type": "constant_value",
                "label": "One",
                "params": {"value": 1},
            },
            {
                "id": "eligible",
                "type": "comparison",
                "label": "Allow ATR dip execution",
                "params": {"comparison": "equals"},
            },
        ],
        "connections": [
            {"source": "enabled", "target": "eligible", "target_input": "value1"},
            {"source": "one", "target": "eligible", "target_input": "value2"},
        ],
    }


def regime_accumulation_graph() -> dict[str, Any]:
    """An experimental shared downtrend/range filter, never an optimized claim."""
    from service.accumulation_strategy import build_accumulation_strategy_document

    graph = legacy_accumulation_graph(
        build_accumulation_strategy_document(),
        "regime_accumulation",
        "Downtrend / sideways accumulation",
        True,
    )
    graph["description"] = (
        "Experimental 4h EMA-slope/ADX regime gate with an exchange-timeframe ATR discount. Filters detected uptrends on subsequent buys; manual accumulation exits."
    )
    graph["nodes"], graph["connections"] = [], []

    def node(key: str, kind: str, label: str, **params: Any) -> str:
        index = len(graph["nodes"])
        graph["nodes"].append(
            {
                "id": key,
                "type": kind,
                "label": label,
                "params": params,
                "position": {"x": (index % 4) * 280, "y": (index // 4) * 160},
            }
        )
        return key

    def comparison(key: str, left: str, op: str, right: str | float) -> str:
        if not isinstance(right, str):
            right = node(key + "_threshold", "constant_value", str(right), value=right)
        node(key, "comparison", key.replace("_", " "), comparison=op)
        graph["connections"].extend(
            [
                {"source": left, "target": key, "target_input": "value1"},
                {"source": right, "target": key, "target_input": "value2"},
            ]
        )
        return key

    def combine(key: str, kind: str, *inputs: str) -> str:
        node(key, kind, key.replace("_", " "))
        graph["connections"].extend(
            {"source": source, "target": key} for source in inputs
        )
        return key

    slope = node(
        "slope",
        "indicator",
        "4h EMA50 slope / ATR",
        indicator="ema_slope",
        length=50,
        slope_period=6,
        atr_length=14,
        timeframe="4h",
        sample="current",
    )
    adx = node(
        "adx",
        "indicator",
        "4h trend strength",
        indicator="adx",
        length=14,
        timeframe="4h",
        sample="current",
    )
    minus = node(
        "minus",
        "indicator",
        "4h -DI",
        indicator="minus_di",
        length=14,
        timeframe="4h",
        sample="current",
    )
    plus = node(
        "plus",
        "indicator",
        "4h +DI",
        indicator="plus_di",
        length=14,
        timeframe="4h",
        sample="current",
    )
    falling = comparison("falling_slope", slope, "less_than", -0.1)
    bearish = comparison("bearish_direction", minus, "greater_than", plus)
    down = combine("downtrend", "all", falling, bearish)
    flat_low = comparison("flat_lower", slope, "greater_or_equal", -0.1)
    flat_high = comparison("flat_upper", slope, "less_or_equal", 0.1)
    weak = comparison("weak_trend", adx, "less_than", 20.0)
    sideways = combine("sideways", "all", flat_low, flat_high, weak)
    regime = combine("eligible_market", "any", down, sideways)
    distance = node(
        "discount",
        "indicator",
        "Base timeframe EMA20 discount / ATR",
        indicator="ema_distance_atr",
        length=20,
        atr_length=14,
        sample="current",
    )
    discounted = comparison(
        "discount_at_least_one_atr", distance, "greater_or_equal", 1.0
    )
    graph["root"] = combine("buy_conditions", "all", regime, discounted)
    return graph
