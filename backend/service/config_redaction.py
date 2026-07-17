"""Redact persisted credentials at public configuration boundaries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

REDACTED_SECRET_VALUE = "__MOONWALKER_SECRET_REDACTED__"

SENSITIVE_CONFIG_KEYS = frozenset(
    {
        "key",
        "secret",
        "marketcap_cmc_api_key",
        "monitoring_telegram_api_hash",
        "monitoring_telegram_bot_token",
    }
)

_SENSITIVE_NESTED_KEYS = frozenset(
    {
        "api_hash",
        "api_key",
        "authorization",
        "bot_token",
        "password",
        "proxy_authorization",
        "secret",
        "token",
        "x_api_key",
    }
)


def _normalized_key(key: Any) -> str:
    """Return a normalized key name for secret classification."""
    return str(key).strip().lower().replace("-", "_")


def _is_sensitive_nested_key(key: Any) -> bool:
    """Return whether a nested configuration key contains a credential."""
    normalized = _normalized_key(key)
    return normalized in _SENSITIVE_NESTED_KEYS or normalized.endswith(
        ("_api_hash", "_api_key", "_password", "_secret", "_token")
    )


def _has_secret_value(value: Any) -> bool:
    """Return whether a credential value is meaningfully configured."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _decode_structured_value(value: Any) -> tuple[Any, bool]:
    """Decode a JSON-backed configuration value and report string encoding."""
    if not isinstance(value, str):
        return value, False
    try:
        return json.loads(value), True
    except json.JSONDecodeError:
        try:
            return json.loads(value.replace("'", '"')), True
        except json.JSONDecodeError:
            return value, False


def _encode_structured_value(value: Any, encoded_as_string: bool) -> Any:
    """Return a structured value using its original storage representation."""
    if encoded_as_string:
        return json.dumps(value)
    return value


def _redact_nested_value(value: Any) -> Any:
    """Return a defensive copy with nested credential fields redacted."""
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, nested_value in value.items():
            redacted[str(key)] = (
                REDACTED_SECRET_VALUE
                if _is_sensitive_nested_key(key) and _has_secret_value(nested_value)
                else _redact_nested_value(nested_value)
            )
        return redacted
    if isinstance(value, list):
        return [_redact_nested_value(item) for item in value]
    return value


def redact_config_value(key: str, value: Any) -> Any:
    """Return a public-safe representation of one configuration value."""
    normalized_key = _normalized_key(key)
    if normalized_key in SENSITIVE_CONFIG_KEYS:
        return REDACTED_SECRET_VALUE if _has_secret_value(value) else value
    if normalized_key != "signal_settings":
        return value

    decoded, encoded_as_string = _decode_structured_value(value)
    if decoded is value and isinstance(value, str):
        return REDACTED_SECRET_VALUE if _has_secret_value(value) else value
    return _encode_structured_value(
        _redact_nested_value(decoded),
        encoded_as_string,
    )


def redact_config_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return a public configuration snapshot without persisted credentials."""
    return {
        str(key): redact_config_value(str(key), value)
        for key, value in snapshot.items()
    }


def _restore_nested_value(incoming: Any, current: Any, *, key: Any = None) -> Any:
    """Restore redacted or empty credential fields from current server state."""
    if _is_sensitive_nested_key(key) and (
        incoming == REDACTED_SECRET_VALUE or not _has_secret_value(incoming)
    ):
        return current
    if isinstance(incoming, Mapping):
        current_mapping = current if isinstance(current, Mapping) else {}
        return {
            str(nested_key): _restore_nested_value(
                nested_value,
                current_mapping.get(nested_key),
                key=nested_key,
            )
            for nested_key, nested_value in incoming.items()
        }
    if isinstance(incoming, list):
        current_list = current if isinstance(current, list) else []
        return [
            _restore_nested_value(
                nested_value,
                current_list[index] if index < len(current_list) else None,
            )
            for index, nested_value in enumerate(incoming)
        ]
    return incoming


def restore_redacted_config_value(key: str, incoming: Any, current: Any) -> Any:
    """Restore one redacted credential value from current server state."""
    normalized_key = _normalized_key(key)
    if normalized_key in SENSITIVE_CONFIG_KEYS:
        if incoming == REDACTED_SECRET_VALUE or not _has_secret_value(incoming):
            return current
        return incoming
    if normalized_key != "signal_settings":
        return incoming

    incoming_decoded, incoming_was_string = _decode_structured_value(incoming)
    current_decoded, _ = _decode_structured_value(current)
    if incoming_decoded == REDACTED_SECRET_VALUE:
        return current
    restored = _restore_nested_value(incoming_decoded, current_decoded)
    return _encode_structured_value(restored, incoming_was_string)


def merge_redacted_config_overrides(
    current: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge client overrides without replacing credentials with redaction markers."""
    merged = dict(current)
    for key, incoming in overrides.items():
        normalized_key = str(key)
        merged[normalized_key] = restore_redacted_config_value(
            normalized_key,
            incoming,
            merged.get(normalized_key),
        )
    return merged
