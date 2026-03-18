"""Helpers for deciding whether config values should be persisted or cleared."""

from __future__ import annotations

from typing import Any


def should_persist_config_value(value_type: str, value_data: Any) -> bool:
    """Return whether a normalized config update should stay in persistent storage."""
    is_numeric_value = isinstance(value_data, (int, float)) and not isinstance(
        value_data, bool
    )
    return (
        bool(value_data)
        or (value_type == "bool" and value_data is False)
        or (value_type in {"int", "float"} and is_numeric_value and value_data == 0)
    )
