"""Validated storage and decision identities for the accumulation foundation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from service.exchange_types import canonical_decimal as exchange_canonical_decimal

MAX_OBSERVATION_BYTES = 32_768
OBSERVATION_SCHEMA_VERSION = 1


class AccumulationLifecycle(StrEnum):
    """Durable lifecycle states; WAIT reasons do not imply a latched pause."""

    VALIDATING = "validating"
    ENABLED = "enabled"
    BLOCKED = "blocked"
    PAUSED = "paused"
    SWITCHING = "switching"
    SELLING_PARTIAL = "selling_partial"
    CLOSING = "closing"
    STOPPED = "stopped"


class AccumulationStateError(ValueError):
    """Persisted accumulation state is invalid and must block evaluation."""


def canonical_decimal(value: str, *, positive: bool = False) -> str:
    """Validate exact monetary strings with the legacy accumulation exception."""
    try:
        return exchange_canonical_decimal(value, positive=positive)
    except ValueError as exc:
        raise AccumulationStateError(str(exc)) from exc


def _integer(payload: dict[str, Any], name: str, minimum: int = 0) -> int:
    value = payload.get(name)
    if type(value) is not int or value < minimum:
        raise AccumulationStateError(f"Invalid {name}.")
    return value


def _text(payload: dict[str, Any], name: str, limit: int) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise AccumulationStateError(f"Invalid {name}.")
    return value


@dataclass(frozen=True)
class AccumulationIdentity:
    """Bind a decision to one account, activation, version and state revision."""

    activation_id: str
    account_scope: str
    generation: str
    state: AccumulationLifecycle
    explicitly_paused: bool
    strategy_version_id: int
    strategy_slug: str
    strategy_version: int
    observation_epoch: int
    baseline_close_ms: int
    revision: int
    consumption_revision: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AccumulationIdentity:
        """Reject incomplete identities instead of defaulting them to fresh state."""
        if not isinstance(payload, dict) or set(payload) != set(
            cls.__dataclass_fields__
        ):
            raise AccumulationStateError("Incomplete or unknown accumulation identity.")
        if type(payload.get("explicitly_paused")) is not bool:
            raise AccumulationStateError("Invalid explicitly_paused.")
        try:
            activation_id = str(UUID(_text(payload, "activation_id", 36)))
            generation = str(UUID(_text(payload, "generation", 36)))
            state = AccumulationLifecycle(payload.get("state"))
        except (TypeError, ValueError) as exc:
            raise AccumulationStateError(
                "Invalid accumulation lifecycle identity."
            ) from exc
        return cls(
            activation_id=activation_id,
            account_scope=_text(payload, "account_scope", 128),
            generation=generation,
            state=state,
            explicitly_paused=payload["explicitly_paused"],
            strategy_version_id=_integer(payload, "strategy_version_id", 1),
            strategy_slug=_text(payload, "strategy_slug", 96),
            strategy_version=_integer(payload, "strategy_version", 1),
            observation_epoch=_integer(payload, "observation_epoch"),
            baseline_close_ms=_integer(payload, "baseline_close_ms"),
            revision=_integer(payload, "revision"),
            consumption_revision=_integer(payload, "consumption_revision"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the validated JSON-compatible decision identity."""
        return asdict(self)


def encode_observations(value: dict[str, Any]) -> str:
    """Bound strategy-private JSON and reject nonfinite/unsupported values."""
    if not isinstance(value, dict):
        raise AccumulationStateError("Observations must be an object.")
    try:
        encoded = json.dumps(
            value, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise AccumulationStateError("Invalid observation JSON.") from exc
    if len(encoded.encode("utf-8")) > MAX_OBSERVATION_BYTES:
        raise AccumulationStateError("Observation state exceeds its bounded size.")
    return encoded


def decode_observations(raw: str, schema_version: int) -> dict[str, Any]:
    """Distinguish corrupt or unsupported persisted state from missing state."""
    if schema_version != OBSERVATION_SCHEMA_VERSION:
        raise AccumulationStateError("Unsupported observation schema version.")
    if len(raw.encode("utf-8")) > MAX_OBSERVATION_BYTES:
        raise AccumulationStateError("Observation state exceeds its bounded size.")
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise AccumulationStateError("Corrupt observation JSON.") from exc
    encode_observations(value)
    return value
