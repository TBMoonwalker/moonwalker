"""Shared lifecycle-mode normalization helpers with no config-module dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from service.spot_campaign_types import TradeLifecycleMode


def _optional_string(value: Any) -> str | None:
    """Normalize optional config strings with whitespace trimming."""
    normalized = str(value or "").strip()
    return normalized or None


def _bool_config_value(value: Any) -> bool:
    """Normalize mixed bool-like config values safely."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    return bool(value)


def normalize_trade_lifecycle_mode(config: dict[str, Any]) -> str:
    """Return the canonical lifecycle mode for mixed legacy/current config rows."""
    raw_mode = _optional_string(config.get("trade_lifecycle_mode"))
    if raw_mode in {
        TradeLifecycleMode.CLASSIC_DCA.value,
        TradeLifecycleMode.SIDESTEP_REENTRY.value,
    }:
        return raw_mode
    return (
        TradeLifecycleMode.SIDESTEP_REENTRY.value
        if _bool_config_value(config.get("sidestep_campaign_enabled", False))
        else TradeLifecycleMode.CLASSIC_DCA.value
    )


def derive_legacy_sidestep_enabled(config: dict[str, Any]) -> bool:
    """Return the compatibility sidestep flag derived from lifecycle mode."""
    return (
        normalize_trade_lifecycle_mode(config)
        == TradeLifecycleMode.SIDESTEP_REENTRY.value
    )


def _int_config_default_only(value: Any, *, default: int) -> int:
    """Normalize an int-like config value while preserving explicit zero values."""
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return default


def _float_config_default_only(value: Any, *, default: float) -> float:
    """Normalize a float-like config value while preserving explicit zero values."""
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class TradeLifecycleConfigView:
    """Typed lifecycle-mode settings derived from the config snapshot."""

    mode: str
    market: str
    enabled: bool
    bearish_exit_strategy: str | None
    reentry_strategy: str | None
    reentry_cooldown_candles: int
    base_order_amount: float

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "TradeLifecycleConfigView":
        """Build normalized lifecycle-mode settings from raw config."""
        reentry_strategy = _optional_string(config.get("sidestep_reentry_strategy"))
        if reentry_strategy is None:
            reentry_strategy = _optional_string(config.get("dca_strategy"))

        return cls(
            mode=normalize_trade_lifecycle_mode(config),
            market=_optional_string(config.get("market")) or "spot",
            enabled=derive_legacy_sidestep_enabled(config),
            bearish_exit_strategy=_optional_string(
                config.get("sidestep_bearish_strategy")
            ),
            reentry_strategy=reentry_strategy,
            reentry_cooldown_candles=max(
                0,
                _int_config_default_only(
                    config.get("sidestep_reentry_cooldown_candles"),
                    default=0,
                ),
            ),
            base_order_amount=max(
                0.0,
                _float_config_default_only(
                    config.get("bo", 0.0),
                    default=0.0,
                ),
            ),
        )

    def is_sidestep_mode(self) -> bool:
        """Return whether sidestep mode is fully enabled for the current market."""
        return (
            self.enabled
            and self.market == "spot"
            and self.mode == TradeLifecycleMode.SIDESTEP_REENTRY.value
        )
