"""Versioned frontend-safe contract for high-risk runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CONFIG_CONTRACT_VERSION = 1
_NO_DEFAULT = object()


@dataclass(frozen=True)
class ConfigFieldContract:
    """Describe one persisted configuration field."""

    value_type: str
    section: str
    default: Any = _NO_DEFAULT
    minimum: float | int | None = None
    maximum: float | int | None = None
    enum: tuple[str, ...] | None = None
    sensitive: bool = False
    write_only: bool = False
    read_only: bool = False
    readiness_relevant: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        """Return metadata safe to expose to dashboard clients."""
        payload: dict[str, Any] = {
            "type": self.value_type,
            "section": self.section,
            "sensitive": self.sensitive,
            "write_only": self.write_only,
            "read_only": self.read_only,
            "readiness_relevant": self.readiness_relevant,
        }
        if self.default is not _NO_DEFAULT and not self.sensitive:
            payload["default"] = self.default
        if self.minimum is not None:
            payload["minimum"] = self.minimum
        if self.maximum is not None:
            payload["maximum"] = self.maximum
        if self.enum is not None:
            payload["enum"] = list(self.enum)
        return payload


CONFIG_FIELDS: dict[str, ConfigFieldContract] = {
    "sidestep_confirm_closed_candle": ConfigFieldContract("bool", "sidestep", False),
    "sidestep_reentry_max_premium_pct": ConfigFieldContract(
        "float", "sidestep", 0.0, minimum=0, maximum=100
    ),
    "sidestep_exit_max_market_fallback_slippage_pct": ConfigFieldContract(
        "float", "sidestep", 0.0, minimum=0, maximum=100
    ),
    "ss": ConfigFieldContract("float", "recovery_dca", 1.6, minimum=0),
    "dynamic_so_sizing_mode": ConfigFieldContract(
        "str",
        "recovery_dca",
        "legacy_factors",
        enum=("legacy_factors", "recovery_shadow", "recovery_target"),
        readiness_relevant=True,
    ),
    "dynamic_so_atr_timeframe": ConfigFieldContract(
        "str",
        "recovery_dca",
        "trading",
    ),
    "dynamic_so_atr_length": ConfigFieldContract(
        "int",
        "recovery_dca",
        14,
        minimum=2,
        maximum=500,
    ),
    "dynamic_so_spacing_atr_multiplier": ConfigFieldContract(
        "float", "recovery_dca", 3.0, minimum=0
    ),
    "dynamic_so_recovery_atr_multiplier": ConfigFieldContract(
        "float", "recovery_dca", 5.5, minimum=0
    ),
    "dynamic_so_recovery_min_pct": ConfigFieldContract(
        "float", "recovery_dca", 12.0, minimum=0, maximum=100
    ),
    "dynamic_so_recovery_max_pct": ConfigFieldContract(
        "float", "recovery_dca", 30.0, minimum=0, maximum=100
    ),
    "dynamic_so_max_deal_quote": ConfigFieldContract(
        "float",
        "recovery_dca",
        250.0,
        minimum=0,
        readiness_relevant=True,
    ),
    "dynamic_so_min_tp_improvement_pct": ConfigFieldContract(
        "float", "recovery_dca", 5.0, minimum=0, maximum=100
    ),
    "dynamic_so_execution_guard_enabled": ConfigFieldContract(
        "bool", "recovery_dca", True
    ),
    "dynamic_so_execution_drift_atr_fraction": ConfigFieldContract(
        "float", "recovery_dca", 0.25, minimum=0
    ),
    "dynamic_so_execution_drift_min_pct": ConfigFieldContract(
        "float", "recovery_dca", 0.15, minimum=0
    ),
    "dynamic_so_execution_drift_max_pct": ConfigFieldContract(
        "float", "recovery_dca", 0.5, minimum=0
    ),
    "delisting_protection_enabled": ConfigFieldContract(
        "bool", "signal", False, readiness_relevant=True
    ),
    "delisting_schedule_use_trading_credentials": ConfigFieldContract(
        "bool", "signal", False
    ),
    "delisting_schedule_api_key": ConfigFieldContract(
        "str",
        "signal",
        "",
        sensitive=True,
        write_only=True,
    ),
    "delisting_schedule_api_secret": ConfigFieldContract(
        "str",
        "signal",
        "",
        sensitive=True,
        write_only=True,
    ),
    "ai_trust_enabled": ConfigFieldContract(
        "bool", "ai_trust", False, readiness_relevant=True
    ),
    "ai_trust_enforce_warnings": ConfigFieldContract(
        "bool", "ai_trust", False, readiness_relevant=True
    ),
    "ai_trust_ollama_base_url": ConfigFieldContract(
        "str", "ai_trust", "http://localhost:11434", readiness_relevant=True
    ),
    "ai_trust_ollama_model": ConfigFieldContract(
        "str", "ai_trust", "", readiness_relevant=True
    ),
    "ai_trust_timeout_ms": ConfigFieldContract(
        "int", "ai_trust", 10_000, minimum=250, maximum=120_000
    ),
    "ai_trust_max_retries": ConfigFieldContract(
        "int", "ai_trust", 0, minimum=0, maximum=2
    ),
    "ai_trust_runtime_status": ConfigFieldContract(
        "str",
        "ai_trust",
        "ok",
        enum=("ok", "provider_unavailable", "warning_blocked"),
        read_only=True,
    ),
}


def config_contract_defaults() -> dict[str, Any]:
    """Return runtime defaults declared by the canonical contract."""
    return {
        key: field.default
        for key, field in CONFIG_FIELDS.items()
        if field.default is not _NO_DEFAULT
    }


def public_config_contract() -> dict[str, Any]:
    """Return the versioned frontend-safe contract."""
    return {
        "version": CONFIG_CONTRACT_VERSION,
        "fields": {
            key: CONFIG_FIELDS[key].to_public_dict() for key in sorted(CONFIG_FIELDS)
        },
    }
