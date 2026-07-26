"""Canonical persisted contract for signal-plugin settings."""

from __future__ import annotations

import json
import math
from typing import Any

SIGNAL_SETTINGS_SCHEMA_VERSION = 1
_STRING_FIELDS = frozenset(
    {
        "api_url",
        "api_key",
        "api_version",
        "csv_source",
        "websocket_url",
        "required_decision",
    }
)
_STRING_LIST_FIELDS = frozenset(
    {
        "accepted_exchanges",
        "accepted_market_states",
    }
)
_SIGNAL_ID_LIST_FIELDS = frozenset({"allowed_signals"})
_NUMBER_FIELDS = frozenset(
    {
        "min_confidence",
        "reconnect_delay_seconds",
        "max_error_reconnect_delay_seconds",
    }
)
_OPEN_JSON_FIELDS = frozenset({"headers", "subscribe_message"})
_KNOWN_FIELDS = (
    _STRING_FIELDS
    | _STRING_LIST_FIELDS
    | _SIGNAL_ID_LIST_FIELDS
    | _NUMBER_FIELDS
    | _OPEN_JSON_FIELDS
    | {"schema_version"}
)


class SignalSettingsError(ValueError):
    """Raised when signal settings do not match the persisted contract."""


def _validate_string_list_field(key: str, value: Any) -> None:
    """Validate a list-like signal setting."""
    if isinstance(value, str):
        return
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SignalSettingsError(
            f"signal_settings.{key} must be a string or a list of strings."
        )


def canonicalize_signal_settings(raw_value: Any) -> dict[str, Any]:
    """Return validated versioned settings from object or JSON input."""
    if raw_value is None:
        payload: Any = {}
    elif isinstance(raw_value, dict):
        payload = dict(raw_value)
    elif isinstance(raw_value, str):
        raw_text = raw_value.strip()
        if not raw_text:
            payload = {}
        else:
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise SignalSettingsError(
                    "signal_settings must contain valid JSON."
                ) from exc
    else:
        raise SignalSettingsError("signal_settings must be a JSON object.")

    if not isinstance(payload, dict):
        raise SignalSettingsError("signal_settings must be a JSON object.")

    unknown_fields = sorted(set(payload) - _KNOWN_FIELDS)
    if unknown_fields:
        raise SignalSettingsError(
            "signal_settings contains unknown fields: "
            + ", ".join(str(field) for field in unknown_fields)
        )

    schema_version = payload.get("schema_version", SIGNAL_SETTINGS_SCHEMA_VERSION)
    if (
        type(schema_version) is not int
        or schema_version != SIGNAL_SETTINGS_SCHEMA_VERSION
    ):
        raise SignalSettingsError(
            f"signal_settings.schema_version must be {SIGNAL_SETTINGS_SCHEMA_VERSION}."
        )

    for key in _STRING_FIELDS:
        value = payload.get(key)
        if value is not None and not isinstance(value, str):
            raise SignalSettingsError(f"signal_settings.{key} must be a string.")
    for key in _STRING_LIST_FIELDS:
        value = payload.get(key)
        if value is not None:
            _validate_string_list_field(key, value)
    for key in _SIGNAL_ID_LIST_FIELDS:
        value = payload.get(key)
        if value is not None and (
            not isinstance(value, list)
            or any(
                isinstance(item, bool) or not isinstance(item, (int, str))
                for item in value
            )
        ):
            raise SignalSettingsError(
                f"signal_settings.{key} must be a list of string or integer IDs."
            )
    for key in _NUMBER_FIELDS:
        value = payload.get(key)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise SignalSettingsError(f"signal_settings.{key} must be a finite number.")
    headers = payload.get("headers")
    if headers is not None and not isinstance(headers, dict):
        raise SignalSettingsError("signal_settings.headers must be a JSON object.")

    return {
        **payload,
        "schema_version": SIGNAL_SETTINGS_SCHEMA_VERSION,
    }


def serialize_signal_settings(raw_value: Any) -> str:
    """Return stable canonical JSON for database persistence."""
    return json.dumps(
        canonicalize_signal_settings(raw_value),
        sort_keys=True,
        separators=(",", ":"),
    )
