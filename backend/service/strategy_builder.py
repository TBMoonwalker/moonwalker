"""Stable public facade for Strategy Builder services."""

from service.strategy_catalog import (
    BUILTIN_STRATEGIES,
    BUILTIN_STRATEGY_BY_SLUG,
    NODE_PALETTE,
    PUBLIC_BUILTIN_SLUGS,
    STRATEGY_IR_SCHEMA_VERSION,
    BuiltinStrategySpec,
)
from service.strategy_persistence import (
    build_builtin_ir,
    build_strategy_explanation,
    create_blank_strategy,
    delete_custom_strategy,
    duplicate_strategy,
    get_strategy_detail,
    list_strategy_options,
    list_strategy_summaries,
    normalize_strategy_slug,
    promote_strategy_version,
    seed_builtin_strategies,
    validate_strategy_ir,
)

__all__ = [
    "BUILTIN_STRATEGIES",
    "BUILTIN_STRATEGY_BY_SLUG",
    "NODE_PALETTE",
    "PUBLIC_BUILTIN_SLUGS",
    "STRATEGY_IR_SCHEMA_VERSION",
    "BuiltinStrategySpec",
    "build_builtin_ir",
    "build_strategy_explanation",
    "create_blank_strategy",
    "delete_custom_strategy",
    "duplicate_strategy",
    "get_strategy_detail",
    "list_strategy_options",
    "list_strategy_summaries",
    "normalize_strategy_slug",
    "promote_strategy_version",
    "seed_builtin_strategies",
    "validate_strategy_ir",
]
