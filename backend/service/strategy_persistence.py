"""Persistence and versioning application service for Strategy Builder."""

from __future__ import annotations

import asyncio
import copy
import json
import re
from datetime import datetime, timezone
from typing import Any

import helper
import model
from service.strategy_catalog import (
    BUILTIN_STRATEGIES,
    BUILTIN_STRATEGY_BY_SLUG,
    CUSTOM_SLUG_PREFIX,
    NODE_PALETTE,
    STRATEGY_IR_SCHEMA_VERSION,
    STRATEGY_KIND_BUILTIN,
    STRATEGY_KIND_CUSTOM,
    SUPPORTED_INDICATORS,
    BuiltinStrategySpec,
)
from service.strategy_ir import validate_strategy_ir_document
from tortoise.transactions import in_transaction

logging = helper.LoggerFactory.get_logger("logs/config.log", "strategy_builder")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,94}$")
_STRATEGY_PROMOTION_LOCK = asyncio.Lock()


def _utc_now_iso() -> str:
    """Return the current UTC time in API-friendly ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    """Serialize JSON consistently for persistence."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str | None, fallback: Any) -> Any:
    """Deserialize JSON with a defensive fallback."""
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def build_builtin_ir(spec: BuiltinStrategySpec) -> dict[str, Any]:
    """Return the Moonwalker IR for a built-in strategy."""
    if spec.slug in {"ema20_swing", "ema20_swing_reverse"}:
        return _build_ema20_swing_ir(spec)
    if spec.slug == "ema_down":
        return _build_ema_down_ir(spec)
    if spec.slug == "ema_low":
        return _build_ema_low_ir(spec)
    if spec.slug == "ema_swing":
        return _build_ema_swing_ir(spec)
    if spec.slug == "bollinger_buy":
        return _build_bollinger_buy_ir(spec)
    decision_node = _node(
        "decision",
        spec.node_type,
        spec.name,
        copy.deepcopy(spec.params),
        260,
        120,
    )
    return _builtin_ir(spec, [decision_node], [])


def _builtin_ir(
    spec: BuiltinStrategySpec,
    nodes: list[dict[str, Any]],
    connections: list[dict[str, str]],
) -> dict[str, Any]:
    """Return common built-in IR payload."""
    return {
        "schema_version": STRATEGY_IR_SCHEMA_VERSION,
        "slug": spec.slug,
        "name": spec.name,
        "description": spec.description,
        "kind": STRATEGY_KIND_BUILTIN,
        "root": "decision",
        "nodes": nodes,
        "connections": connections,
        "metadata": {
            "min_history_candles": spec.min_history_candles,
            "required_methods": list(spec.required_methods),
            "source": "builtin_python_parity",
        },
    }


def _node(
    node_id: str,
    node_type: str,
    label: str,
    params: dict[str, Any],
    x: int,
    y: int,
) -> dict[str, Any]:
    """Return a graph node with a stable position."""
    return {
        "id": node_id,
        "type": node_type,
        "label": label,
        "params": params,
        "position": {"x": x, "y": y},
    }


def _comparison(
    node_id: str,
    label: str,
    comparison: str,
    x: int,
    y: int,
) -> dict[str, Any]:
    """Return a comparison node."""
    return _node(node_id, "comparison", label, {"comparison": comparison}, x, y)


def _indicator(
    node_id: str,
    indicator: str,
    label: str,
    x: int,
    y: int,
    *,
    length: int | None = None,
    sample: str | None = None,
) -> dict[str, Any]:
    """Return a configured indicator value node."""
    params: dict[str, Any] = {"indicator": indicator}
    if length is not None:
        params["length"] = length
    if sample is not None:
        params["sample"] = sample
    return _node(node_id, "indicator", label, params, x, y)


def _comparison_edges(
    value1: str,
    value2: str,
    target: str,
) -> list[dict[str, str]]:
    """Return value1/value2 edges for one comparison node."""
    return [
        {"source": value1, "target": target, "target_input": "value1"},
        {"source": value2, "target": target, "target_input": "value2"},
    ]


def _build_ema_down_ir(spec: BuiltinStrategySpec) -> dict[str, Any]:
    """Return EMA down as explicit EMA value and comparison nodes."""
    nodes = [
        _indicator(
            "ema20",
            "ema",
            "EMA 20 current",
            80,
            120,
            length=20,
            sample="current",
        ),
        _indicator(
            "ema50",
            "ema",
            "EMA 50 current",
            80,
            280,
            length=50,
            sample="current",
        ),
        _comparison("decision", "EMA 20 below EMA 50", "less_than", 360, 200),
    ]
    return _builtin_ir(spec, nodes, _comparison_edges("ema20", "ema50", "decision"))


def _build_bollinger_buy_ir(spec: BuiltinStrategySpec) -> dict[str, Any]:
    """Return the lower-band wick and trend-filtered Bollinger buy graph."""
    nodes = [
        _node(
            "low_previous",
            "low_price",
            "Low previous",
            {"lookback": 202, "sample": "previous"},
            40,
            20,
        ),
        _node(
            "low_current",
            "low_price",
            "Low current",
            {"lookback": 202, "sample": "current"},
            40,
            100,
        ),
        _indicator(
            "lower_previous",
            "bollinger_lower",
            "Bollinger lower previous",
            40,
            180,
            length=20,
            sample="previous",
        ),
        _indicator(
            "lower_current",
            "bollinger_lower",
            "Bollinger lower current",
            40,
            260,
            length=20,
            sample="current",
        ),
        _indicator(
            "middle_previous",
            "bollinger_middle",
            "Bollinger middle previous",
            40,
            340,
            length=20,
            sample="previous",
        ),
        _indicator(
            "middle_current",
            "bollinger_middle",
            "Bollinger middle current",
            40,
            420,
            length=20,
            sample="current",
        ),
        _indicator(
            "ema50_current",
            "ema",
            "EMA 50 current",
            40,
            580,
            length=50,
            sample="current",
        ),
        _indicator(
            "ema100_current",
            "ema",
            "EMA 100 current",
            40,
            740,
            length=100,
            sample="current",
        ),
        _indicator(
            "rsi14", "rsi", "RSI 14 current", 40, 820, length=14, sample="current"
        ),
        _indicator(
            "bandwidth",
            "bollinger_bandwidth",
            "Bollinger bandwidth percent",
            40,
            900,
            length=20,
            sample="current",
        ),
        _node(
            "rsi_limit", "constant_value", "RSI threshold 50", {"value": 50.0}, 40, 980
        ),
        _node(
            "bandwidth_limit",
            "constant_value",
            "Minimum bandwidth percent 2",
            {"value": 2.0},
            40,
            1060,
        ),
        _comparison(
            "was_above_lower",
            "Previous low at or above lower band",
            "greater_or_equal",
            350,
            40,
        ),
        _comparison(
            "breaks_lower",
            "Current low below lower band",
            "less_than",
            350,
            140,
        ),
        _node("lower_break", "all", "Wick crosses lower band", {}, 620, 90),
        _comparison("band_uptrend", "Middle band rising", "greater_than", 350, 300),
        _comparison(
            "band_downtrend",
            "Middle band flat or falling",
            "less_or_equal",
            350,
            390,
        ),
        _comparison(
            "under_ema50",
            "Current low below EMA 50",
            "less_than",
            350,
            530,
        ),
        _node(
            "uptrend_branch",
            "all",
            "Uptrend: low below EMA 50",
            {},
            870,
            370,
        ),
        _comparison(
            "under_ema100",
            "Current low below EMA 100",
            "less_than",
            350,
            700,
        ),
        _node(
            "downtrend_branch",
            "all",
            "Downtrend: low below EMA 100",
            {},
            870,
            650,
        ),
        _node("trend_cross", "any", "Trend-dependent EMA cross", {}, 1100, 500),
        _comparison("rsi_under_50", "RSI 14 below 50", "less_than", 350, 850),
        _comparison(
            "bands_are_wide",
            "Bollinger bandwidth at least 2 percent",
            "greater_or_equal",
            350,
            960,
        ),
        _node("decision", "all", "All Bollinger buy conditions", {}, 1360, 420),
    ]
    connections = [
        *_comparison_edges("low_previous", "lower_previous", "was_above_lower"),
        *_comparison_edges("low_current", "lower_current", "breaks_lower"),
        {"source": "was_above_lower", "target": "lower_break"},
        {"source": "breaks_lower", "target": "lower_break"},
        *_comparison_edges("middle_current", "middle_previous", "band_uptrend"),
        *_comparison_edges("middle_current", "middle_previous", "band_downtrend"),
        *_comparison_edges("low_current", "ema50_current", "under_ema50"),
        {"source": "band_uptrend", "target": "uptrend_branch"},
        {"source": "under_ema50", "target": "uptrend_branch"},
        *_comparison_edges("low_current", "ema100_current", "under_ema100"),
        {"source": "band_downtrend", "target": "downtrend_branch"},
        {"source": "under_ema100", "target": "downtrend_branch"},
        {"source": "uptrend_branch", "target": "trend_cross"},
        {"source": "downtrend_branch", "target": "trend_cross"},
        *_comparison_edges("rsi14", "rsi_limit", "rsi_under_50"),
        *_comparison_edges("bandwidth", "bandwidth_limit", "bands_are_wide"),
        {"source": "lower_break", "target": "decision"},
        {"source": "trend_cross", "target": "decision"},
        {"source": "rsi_under_50", "target": "decision"},
        {"source": "bands_are_wide", "target": "decision"},
    ]
    return _builtin_ir(spec, nodes, connections)


def _build_ema_low_ir(spec: BuiltinStrategySpec) -> dict[str, Any]:
    """Return EMA low rebound as explicit trend and price comparison nodes."""
    nodes = [
        _indicator(
            "ema20",
            "ema",
            "EMA 20 current",
            80,
            60,
            length=20,
            sample="current",
        ),
        _indicator(
            "ema50",
            "ema",
            "EMA 50 current",
            80,
            180,
            length=50,
            sample="current",
        ),
        _indicator(
            "ema100",
            "ema",
            "EMA 100 current",
            80,
            300,
            length=100,
            sample="current",
        ),
        _indicator(
            "ema200",
            "ema",
            "EMA 200 current",
            80,
            420,
            length=200,
            sample="current",
        ),
        _node(
            "close_previous",
            "close_price",
            "Close previous",
            {"lookback": 5, "sample": "previous"},
            80,
            560,
        ),
        _node(
            "close_two_back",
            "close_price",
            "Close two back",
            {"lookback": 5, "sample": "two_back"},
            80,
            680,
        ),
        _comparison("ema20_below_ema200", "EMA 20 below EMA 200", "less_than", 360, 80),
        _comparison(
            "ema50_below_ema200", "EMA 50 below EMA 200", "less_than", 360, 220
        ),
        _comparison(
            "ema100_below_ema200", "EMA 100 below EMA 200", "less_than", 360, 360
        ),
        _comparison(
            "close_above_ema20", "Close previous above EMA 20", "greater_than", 360, 540
        ),
        _comparison(
            "close_two_back_below_ema20",
            "Close two back below EMA 20",
            "less_than",
            360,
            680,
        ),
        _node("decision", "all", "All conditions", {}, 680, 360),
    ]
    connections = [
        *_comparison_edges("ema20", "ema200", "ema20_below_ema200"),
        *_comparison_edges("ema50", "ema200", "ema50_below_ema200"),
        *_comparison_edges("ema100", "ema200", "ema100_below_ema200"),
        *_comparison_edges("close_previous", "ema20", "close_above_ema20"),
        *_comparison_edges("close_two_back", "ema20", "close_two_back_below_ema20"),
        {"source": "ema20_below_ema200", "target": "decision"},
        {"source": "ema50_below_ema200", "target": "decision"},
        {"source": "ema100_below_ema200", "target": "decision"},
        {"source": "close_above_ema20", "target": "decision"},
        {"source": "close_two_back_below_ema20", "target": "decision"},
    ]
    return _builtin_ir(spec, nodes, connections)


def _build_ema_swing_ir(spec: BuiltinStrategySpec) -> dict[str, Any]:
    """Return EMA swing as explicit trend, swing, and state nodes."""
    nodes = [
        _indicator(
            "ema20",
            "ema",
            "EMA 20 current",
            80,
            40,
            length=20,
            sample="current",
        ),
        _indicator(
            "ema50",
            "ema",
            "EMA 50 current",
            80,
            160,
            length=50,
            sample="current",
        ),
        _indicator(
            "ema100",
            "ema",
            "EMA 100 current",
            80,
            280,
            length=100,
            sample="current",
        ),
        _indicator(
            "ema200",
            "ema",
            "EMA 200 current",
            80,
            400,
            length=200,
            sample="current",
        ),
        _node(
            "close_current",
            "close_price",
            "Close current",
            {"lookback": 8, "sample": "current"},
            80,
            540,
        ),
        _node(
            "close_previous",
            "close_price",
            "Close previous",
            {"lookback": 8, "sample": "previous"},
            80,
            660,
        ),
        _node(
            "close_two_back",
            "close_price",
            "Close two back",
            {"lookback": 8, "sample": "two_back"},
            80,
            780,
        ),
        _comparison("ema20_below_ema200", "EMA 20 below EMA 200", "less_than", 360, 60),
        _comparison(
            "ema50_below_ema200", "EMA 50 below EMA 200", "less_than", 360, 200
        ),
        _comparison(
            "ema100_below_ema200", "EMA 100 below EMA 200", "less_than", 360, 340
        ),
        _comparison(
            "close_current_above_ema20",
            "Close current above EMA 20",
            "greater_than",
            360,
            520,
        ),
        _comparison(
            "close_previous_below_ema20",
            "Close previous below EMA 20",
            "less_than",
            360,
            660,
        ),
        _node(
            "higher_swing_low",
            "swing_low_state",
            "Current swing low above previous",
            copy.deepcopy(spec.params),
            640,
            700,
        ),
        _node("decision", "all", "All conditions", {}, 900, 360),
    ]
    connections = [
        *_comparison_edges("ema20", "ema200", "ema20_below_ema200"),
        *_comparison_edges("ema50", "ema200", "ema50_below_ema200"),
        *_comparison_edges("ema100", "ema200", "ema100_below_ema200"),
        *_comparison_edges("close_current", "ema20", "close_current_above_ema20"),
        *_comparison_edges("close_previous", "ema20", "close_previous_below_ema20"),
        {"source": "close_previous", "target": "higher_swing_low"},
        {"source": "close_two_back", "target": "higher_swing_low"},
        {"source": "ema20_below_ema200", "target": "decision"},
        {"source": "ema50_below_ema200", "target": "decision"},
        {"source": "ema100_below_ema200", "target": "decision"},
        {"source": "close_current_above_ema20", "target": "decision"},
        {"source": "close_previous_below_ema20", "target": "decision"},
        {"source": "higher_swing_low", "target": "decision"},
    ]
    return _builtin_ir(spec, nodes, connections)


def _build_ema20_swing_ir(spec: BuiltinStrategySpec) -> dict[str, Any]:
    """Return a decomposed EMA20 swing graph matching the Python strategy."""
    direction = str(spec.params.get("direction") or "bullish")
    bearish = direction == "bearish"
    comparison = "less_than" if bearish else "greater_than"
    price_label = "Close below EMA20" if bearish else "Close above EMA20"
    trend_label = (
        "EMA current below previous" if bearish else "EMA current above previous"
    )
    nodes = [
        _indicator(
            "ema20_previous",
            "ema",
            "EMA 20 previous",
            80,
            80,
            length=20,
            sample="previous",
        ),
        _indicator(
            "ema20_current",
            "ema",
            "EMA 20 current",
            80,
            220,
            length=20,
            sample="current",
        ),
        {
            "id": "close_current",
            "type": "close_price",
            "label": "Close price",
            "params": {"lookback": 50, "sample": "current"},
            "position": {"x": 80, "y": 360},
        },
        {
            "id": "ema_trend_compare",
            "type": "comparison",
            "label": trend_label,
            "params": {"comparison": comparison},
            "position": {"x": 350, "y": 130},
        },
        {
            "id": "close_compare",
            "type": "comparison",
            "label": price_label,
            "params": {"comparison": comparison},
            "position": {"x": 350, "y": 310},
        },
        {
            "id": "fresh_state",
            "type": "fresh_signal_state",
            "label": "Fresh swing state",
            "params": {
                "direction": direction,
                "state_key": spec.params.get(
                    "state_key",
                    f"ema20_swing:{direction}",
                ),
            },
            "position": {"x": 350, "y": 470},
        },
        {
            "id": "decision",
            "type": "all",
            "label": "All conditions",
            "params": {},
            "position": {"x": 650, "y": 290},
        },
    ]
    return {
        "schema_version": STRATEGY_IR_SCHEMA_VERSION,
        "slug": spec.slug,
        "name": spec.name,
        "description": spec.description,
        "kind": STRATEGY_KIND_BUILTIN,
        "root": "decision",
        "nodes": nodes,
        "connections": [
            {
                "source": "ema20_current",
                "target": "ema_trend_compare",
                "target_input": "value1",
            },
            {
                "source": "ema20_previous",
                "target": "ema_trend_compare",
                "target_input": "value2",
            },
            {
                "source": "close_current",
                "target": "close_compare",
                "target_input": "value1",
            },
            {
                "source": "ema20_current",
                "target": "close_compare",
                "target_input": "value2",
            },
            {"source": "ema20_current", "target": "fresh_state"},
            {"source": "close_current", "target": "fresh_state"},
            {"source": "ema_trend_compare", "target": "decision"},
            {"source": "close_compare", "target": "decision"},
            {"source": "fresh_state", "target": "decision"},
        ],
        "metadata": {
            "min_history_candles": spec.min_history_candles,
            "required_methods": list(spec.required_methods),
            "source": "builtin_python_parity",
        },
    }


def normalize_strategy_slug(name: str) -> str:
    """Return a custom strategy slug from user-facing text."""
    normalized = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    if not normalized:
        normalized = "strategy"
    if not normalized.startswith(CUSTOM_SLUG_PREFIX):
        normalized = f"{CUSTOM_SLUG_PREFIX}{normalized}"
    return normalized[:95]


def validate_strategy_ir(ir: dict[str, Any]) -> dict[str, Any]:
    """Validate the persisted Moonwalker strategy IR."""
    return validate_strategy_ir_document(
        ir,
        schema_version=STRATEGY_IR_SCHEMA_VERSION,
        palette_types={node["type"] for node in NODE_PALETTE},
        supported_indicators=SUPPORTED_INDICATORS,
        checked_at_factory=_utc_now_iso,
    )


async def seed_builtin_strategies() -> None:
    """Ensure built-in Strategy Builder definitions exist."""
    await _delete_retired_builtin_strategies()
    for spec in BUILTIN_STRATEGIES:
        ir = build_builtin_ir(spec)
        validation = validate_strategy_ir(ir)
        definition = await model.StrategyDefinition.get_or_none(slug=spec.slug)
        if definition is None:
            definition = await model.StrategyDefinition.create(
                slug=spec.slug,
                name=spec.name,
                description=spec.description,
                is_builtin=True,
                active_version=1,
                draft_version=1,
                validation_status=validation["status"],
            )
        else:
            changed = False
            if not definition.is_builtin:
                definition.is_builtin = True
                changed = True
            if definition.name != spec.name:
                definition.name = spec.name
                changed = True
            if definition.description != spec.description:
                definition.description = spec.description
                changed = True
            if definition.active_version is None:
                definition.active_version = 1
                changed = True
            if definition.draft_version < 1:
                definition.draft_version = 1
                changed = True
            if definition.validation_status != validation["status"]:
                definition.validation_status = validation["status"]
                changed = True
            if changed:
                await definition.save()

        version = await model.StrategyVersion.get_or_none(
            strategy_slug=spec.slug,
            version=1,
        )
        next_ir_json = _json_dumps(ir)
        next_validation_json = _json_dumps(validation)
        next_explanation = build_strategy_explanation(ir, validation)
        if version is None:
            await model.StrategyVersion.create(
                strategy_slug=spec.slug,
                version=1,
                ir_json=next_ir_json,
                validation_json=next_validation_json,
                explanation=next_explanation,
                activated_at=datetime.now(timezone.utc),
            )
        elif (
            version.ir_json != next_ir_json
            or version.validation_json != next_validation_json
            or version.explanation != next_explanation
        ):
            version.ir_json = next_ir_json
            version.validation_json = next_validation_json
            version.explanation = next_explanation
            if version.activated_at is None:
                version.activated_at = datetime.now(timezone.utc)
            await version.save()


async def _delete_retired_builtin_strategies() -> None:
    """Remove built-ins that no longer exist in the source catalog."""
    rows = await model.StrategyDefinition.filter(is_builtin=True)
    retired_rows = [
        row for row in rows if str(row.slug) not in BUILTIN_STRATEGY_BY_SLUG
    ]
    if not retired_rows:
        return

    from service.strategy_runtime import invalidate_strategy_runtime_cache

    for definition in retired_rows:
        slug = str(definition.slug)
        await model.StrategyVersion.filter(strategy_slug=slug).delete()
        await model.StrategyGraphState.filter(strategy_slug=slug).delete()
        await definition.delete()
        invalidate_strategy_runtime_cache(slug)


def _empty_custom_ir(slug: str, name: str) -> dict[str, Any]:
    """Return an empty custom strategy graph."""
    return {
        "schema_version": STRATEGY_IR_SCHEMA_VERSION,
        "slug": slug,
        "name": name,
        "description": "",
        "kind": STRATEGY_KIND_CUSTOM,
        "root": "",
        "nodes": [],
        "connections": [],
        "metadata": {"source": "strategy_builder_blank"},
    }


async def list_strategy_summaries(include_hidden: bool = False) -> list[dict[str, Any]]:
    """Return strategy summaries for selectors and the builder list."""
    await seed_builtin_strategies()
    rows = await model.StrategyDefinition.all().order_by("is_builtin", "name")
    summaries: list[dict[str, Any]] = []
    for row in rows:
        if not include_hidden and row.slug in _hidden_builtin_slugs():
            continue
        summaries.append(await _definition_summary(row))
    return summaries


async def list_strategy_options() -> list[str]:
    """Return public strategy slugs for selectors."""
    summaries = await list_strategy_summaries(include_hidden=False)
    return [str(summary["slug"]) for summary in summaries if summary["available"]]


async def get_strategy_detail(slug: str) -> dict[str, Any] | None:
    """Return one strategy definition with its active IR."""
    await seed_builtin_strategies()
    definition = await model.StrategyDefinition.get_or_none(slug=slug)
    if definition is None:
        return None
    active_version = await _get_active_version(definition)
    summary = await _definition_summary(definition)
    ir = _json_loads(active_version.ir_json if active_version else None, {})
    validation = _json_loads(
        active_version.validation_json if active_version else None,
        validate_strategy_ir(ir) if isinstance(ir, dict) else {},
    )
    return {
        **summary,
        "ir": ir,
        "validation": validation,
        "explanation": active_version.explanation if active_version else "",
        "palette": list(NODE_PALETTE),
    }


async def duplicate_strategy(
    source_slug: str, name: str | None = None
) -> dict[str, Any]:
    """Create a custom strategy from a built-in or existing custom definition."""
    source = await get_strategy_detail(source_slug)
    if source is None:
        raise ValueError(f"Strategy '{source_slug}' was not found.")

    source_ir = copy.deepcopy(source["ir"])
    display_name = str(name or f"{source['name']} copy").strip()
    base_slug = normalize_strategy_slug(display_name)
    slug = await _unique_strategy_slug(base_slug)
    source_ir["slug"] = slug
    source_ir["name"] = display_name
    source_ir["kind"] = STRATEGY_KIND_CUSTOM
    source_ir.setdefault("metadata", {})["duplicated_from"] = source_slug
    validation = validate_strategy_ir(source_ir)
    explanation = build_strategy_explanation(source_ir, validation)

    await model.StrategyDefinition.create(
        slug=slug,
        name=display_name,
        description=str(source.get("description") or ""),
        is_builtin=False,
        duplicated_from=source_slug,
        active_version=1,
        draft_version=1,
        validation_status=validation["status"],
    )
    await model.StrategyVersion.create(
        strategy_slug=slug,
        version=1,
        ir_json=_json_dumps(source_ir),
        validation_json=_json_dumps(validation),
        explanation=explanation,
        activated_at=datetime.now(timezone.utc),
    )
    from service.strategy_runtime import invalidate_strategy_runtime_cache

    invalidate_strategy_runtime_cache(slug)
    detail = await get_strategy_detail(slug)
    if detail is None:
        raise RuntimeError("Duplicated strategy disappeared before it could be loaded.")
    return detail


async def create_blank_strategy(name: str) -> dict[str, Any]:
    """Create a secondary blank custom strategy."""
    display_name = str(name or "Custom strategy").strip()
    slug = await _unique_strategy_slug(normalize_strategy_slug(display_name))
    ir = _empty_custom_ir(slug, display_name)
    validation = validate_strategy_ir(ir)
    await model.StrategyDefinition.create(
        slug=slug,
        name=display_name,
        description="",
        is_builtin=False,
        active_version=1,
        draft_version=1,
        validation_status=validation["status"],
    )
    await model.StrategyVersion.create(
        strategy_slug=slug,
        version=1,
        ir_json=_json_dumps(ir),
        validation_json=_json_dumps(validation),
        explanation=build_strategy_explanation(ir, validation),
        activated_at=datetime.now(timezone.utc),
    )
    from service.strategy_runtime import invalidate_strategy_runtime_cache

    invalidate_strategy_runtime_cache(slug)
    detail = await get_strategy_detail(slug)
    if detail is None:
        raise RuntimeError("Created strategy disappeared before it could be loaded.")
    return detail


async def delete_custom_strategy(slug: str) -> None:
    """Delete a custom strategy definition and all stored graph state."""
    definition = await model.StrategyDefinition.get_or_none(slug=slug)
    if definition is None:
        raise ValueError(f"Strategy '{slug}' was not found.")
    if definition.is_builtin:
        raise PermissionError("Built-in strategies cannot be deleted.")

    await model.StrategyVersion.filter(strategy_slug=slug).delete()
    await model.StrategyGraphState.filter(strategy_slug=slug).delete()
    await definition.delete()

    from service.strategy_runtime import invalidate_strategy_runtime_cache

    invalidate_strategy_runtime_cache(slug)


async def promote_strategy_version(
    slug: str,
    ir: dict[str, Any],
    base_lock_version: int,
) -> tuple[dict[str, Any], int]:
    """Validate and atomically promote a custom strategy version."""
    async with _STRATEGY_PROMOTION_LOCK:
        definition = await model.StrategyDefinition.get_or_none(slug=slug)
        if definition is None:
            raise ValueError(f"Strategy '{slug}' was not found.")
        if definition.is_builtin:
            raise PermissionError("Built-in strategies are read-only. Duplicate first.")
        if definition.lock_version != base_lock_version:
            return await get_strategy_detail(slug) or {}, 409

        next_ir = copy.deepcopy(ir)
        next_ir["schema_version"] = STRATEGY_IR_SCHEMA_VERSION
        next_ir["slug"] = slug
        next_ir["kind"] = STRATEGY_KIND_CUSTOM
        next_ir["name"] = str(next_ir.get("name") or definition.name)
        validation = validate_strategy_ir(next_ir)
        if validation["status"] != "valid":
            return {
                "strategy": await get_strategy_detail(slug),
                "validation": validation,
            }, 422

        next_version = (definition.active_version or 0) + 1
        async with in_transaction() as connection:
            await model.StrategyVersion.create(
                strategy_slug=slug,
                version=next_version,
                ir_json=_json_dumps(next_ir),
                validation_json=_json_dumps(validation),
                explanation=build_strategy_explanation(next_ir, validation),
                activated_at=datetime.now(timezone.utc),
                using_db=connection,
            )
            definition.name = str(next_ir.get("name") or definition.name)
            definition.description = str(
                next_ir.get("description") or definition.description or ""
            )
            definition.active_version = next_version
            definition.draft_version = next_version
            definition.validation_status = validation["status"]
            definition.lock_version += 1
            await definition.save(using_db=connection)

    from service.strategy_runtime import invalidate_strategy_runtime_cache

    invalidate_strategy_runtime_cache(slug)
    return await get_strategy_detail(slug) or {}, 200


def build_strategy_explanation(ir: dict[str, Any], validation: dict[str, Any]) -> str:
    """Build a plain-language explanation for an operator."""
    nodes = ir.get("nodes") if isinstance(ir.get("nodes"), list) else []
    root = str(ir.get("root") or "decision")
    root_node = next(
        (node for node in nodes if isinstance(node, dict) and node.get("id") == root),
        nodes[0] if nodes else {},
    )
    label = str(root_node.get("label") or ir.get("name") or "Strategy")
    history = validation.get("required_history", {}).get("label", "")
    if validation.get("status") != "valid":
        return (
            f"{label} is not ready to run. Fix the blocking validation errors before "
            "promoting it to the active version."
        )
    return (
        f"{label} runs as a Moonwalker graph. It evaluates the active decision node, "
        f"uses {history.lower()}, and only promotes immutable validated versions."
    )


async def _definition_summary(row: model.StrategyDefinition) -> dict[str, Any]:
    """Return a serialized summary for one definition."""
    active_version = await _get_active_version(row)
    validation = _json_loads(
        active_version.validation_json if active_version else None,
        {"status": row.validation_status},
    )
    unavailable = _missing_indicator_methods(validation)
    return {
        "slug": row.slug,
        "name": row.name,
        "description": row.description or "",
        "kind": STRATEGY_KIND_BUILTIN if row.is_builtin else STRATEGY_KIND_CUSTOM,
        "is_builtin": row.is_builtin,
        "duplicated_from": row.duplicated_from,
        "active_version": row.active_version,
        "draft_version": row.draft_version,
        "lock_version": row.lock_version,
        "validation_status": validation.get("status", row.validation_status),
        "required_history": validation.get("required_history", {}),
        "hook_readiness": validation.get("hook_readiness", []),
        "available": not unavailable and validation.get("status") == "valid",
        "missing_hooks": unavailable,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _get_active_version(
    definition: model.StrategyDefinition,
) -> model.StrategyVersion | None:
    """Return the active immutable version for a definition."""
    if definition.active_version is None:
        return None
    return await model.StrategyVersion.get_or_none(
        strategy_slug=definition.slug,
        version=definition.active_version,
    )


def _missing_indicator_methods(validation: dict[str, Any]) -> list[str]:
    """Return hook names unavailable in the current Indicators service."""
    from service.indicators import Indicators

    missing = []
    for hook in validation.get("hook_readiness", []):
        name = str(hook.get("name") or "")
        if name and not callable(getattr(Indicators, name, None)):
            missing.append(name)
    return missing


def _hidden_builtin_slugs() -> set[str]:
    """Return built-in compatibility aliases that should stay out of selectors."""
    return {strategy.slug for strategy in BUILTIN_STRATEGIES if strategy.hidden}


async def _unique_strategy_slug(base_slug: str) -> str:
    """Return a custom slug that does not exist yet."""
    slug = base_slug
    counter = 2
    while await model.StrategyDefinition.get_or_none(slug=slug) is not None:
        suffix = f"_{counter}"
        slug = f"{base_slug[: 95 - len(suffix)]}{suffix}"
        counter += 1
    if not _SLUG_RE.fullmatch(slug):
        raise ValueError("Strategy slug contains unsupported characters.")
    return slug
