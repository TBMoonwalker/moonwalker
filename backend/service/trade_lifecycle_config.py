"""Shared trade-mode normalization helpers with no config-module dependency."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from service.spot_campaign_types import TradeLifecycleMode


class TradeMode(StrEnum):
    """Canonical operator-facing trade modes."""

    DYNAMIC_DCA = "dynamic_dca"
    SIDESTEP = "sidestep"


class TradeModeConfigErrorCode(StrEnum):
    """Stable trade-mode validation error codes."""

    INVALID_BACKUP_SHAPE = "invalid_backup_shape"
    INVALID_TRADE_MODE = "invalid_trade_mode"
    MISSING_SIDESTEP_REENTRY_STRATEGY = "missing_sidestep_reentry_strategy"
    BLOCKED_LIVE_MODE_SWITCH = "blocked_live_mode_switch"


TRADE_MODE_VALIDATION_KEYS = frozenset(
    {
        "trade_mode",
        "sidestep_reentry_strategy",
        "dca_strategy",
    }
)


def _optional_string(value: Any) -> str | None:
    """Normalize optional config strings with whitespace trimming."""
    normalized = str(value or "").strip()
    return normalized or None


@dataclass(frozen=True)
class TradeModeErrorPayload:
    """Structured operator-safe trade-mode validation payload."""

    code: str
    source: str
    message: str
    safe_fields: dict[str, Any]
    next_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the public JSON payload for API responses."""
        payload = {
            "code": self.code,
            "source": self.source,
            "message": self.message,
            "safe_fields": dict(self.safe_fields),
        }
        if self.next_action is not None:
            payload["next_action"] = self.next_action
        return payload


class TradeModeConfigError(ValueError):
    """Structured validation error shared across startup, save, and restore."""

    def __init__(
        self,
        payload: TradeModeErrorPayload,
        *,
        status_code: int = 409,
    ) -> None:
        super().__init__(payload.message)
        self.payload = payload
        self.status_code = status_code

    def to_response_body(self) -> dict[str, Any]:
        """Return a legacy-safe API response body with structured details."""
        payload = self.payload.to_dict()
        return {
            "error": payload["message"],
            "message": payload["message"],
            "migration_error": payload,
        }


def build_invalid_backup_shape_error(
    *,
    source: str = "restore",
    message: str,
    safe_fields: dict[str, Any] | None = None,
) -> TradeModeConfigError:
    """Build the shared invalid-backup-shape error payload."""
    return TradeModeConfigError(
        TradeModeErrorPayload(
            code=TradeModeConfigErrorCode.INVALID_BACKUP_SHAPE.value,
            source=source,
            message=message,
            safe_fields=safe_fields or {},
        ),
        status_code=400,
    )


def build_invalid_trade_mode_error(
    *,
    source: str,
    message: str,
    safe_fields: dict[str, Any],
) -> TradeModeConfigError:
    """Build the shared invalid-trade-mode error payload."""
    return TradeModeConfigError(
        TradeModeErrorPayload(
            code=TradeModeConfigErrorCode.INVALID_TRADE_MODE.value,
            source=source,
            message=message,
            safe_fields=safe_fields,
            next_action=(
                "Use trade_mode='dynamic_dca' or trade_mode='sidestep', "
                "then save again from a current client."
            ),
        )
    )


def build_missing_sidestep_reentry_strategy_error(
    *,
    source: str,
    safe_fields: dict[str, Any],
) -> TradeModeConfigError:
    """Build the shared missing sidestep strategy error payload."""
    return TradeModeConfigError(
        TradeModeErrorPayload(
            code=TradeModeConfigErrorCode.MISSING_SIDESTEP_REENTRY_STRATEGY.value,
            source=source,
            message=(
                "Sidestep mode requires an explicit sidestep_reentry_strategy "
                "before save or restore can continue."
            ),
            safe_fields=safe_fields,
            next_action=(
                "Choose a sidestep re-entry strategy explicitly and retry the "
                "save or restore."
            ),
        )
    )


def build_blocked_live_mode_switch_error(
    *,
    source: str,
    current_trade_mode: str,
    requested_trade_mode: str,
    open_trade_count: int,
    waiting_campaign_count: int,
) -> TradeModeConfigError:
    """Build the shared blocked-mode-switch error payload."""
    blockers: list[str] = []
    if open_trade_count > 0:
        blockers.append(f"{open_trade_count} open trade(s)")
    if waiting_campaign_count > 0:
        blockers.append(f"{waiting_campaign_count} waiting sidestep campaign(s)")
    blocker_text = ", ".join(blockers) or "active runtime state"
    return TradeModeConfigError(
        TradeModeErrorPayload(
            code=TradeModeConfigErrorCode.BLOCKED_LIVE_MODE_SWITCH.value,
            source=source,
            message=(
                "Cannot switch trade mode while runtime activity still exists: "
                f"{blocker_text}."
            ),
            safe_fields={
                "current_trade_mode": current_trade_mode,
                "requested_trade_mode": requested_trade_mode,
                "open_trade_count": open_trade_count,
                "waiting_campaign_count": waiting_campaign_count,
            },
            next_action=(
                "Close open trades and clear waiting sidestep campaigns before "
                "switching trade modes."
            ),
        )
    )


@dataclass(frozen=True)
class TradeModeSwitchGuard:
    """Cheap runtime status for enabling or blocking trade-mode switches."""

    current_trade_mode: str
    blocked: bool
    open_trade_count: int
    waiting_campaign_count: int
    message: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return the public API payload."""
        return {
            "current_trade_mode": self.current_trade_mode,
            "blocked": self.blocked,
            "can_switch": not self.blocked,
            "open_trade_count": self.open_trade_count,
            "waiting_campaign_count": self.waiting_campaign_count,
            "message": self.message,
        }


@dataclass(frozen=True)
class TradeModeConfigState:
    """Normalized canonical and derived trade-mode settings."""

    trade_mode: str
    lifecycle_mode: str
    dynamic_dca_enabled: bool
    sidestep_enabled: bool
    market: str
    explicit_reentry_strategy: str | None
    effective_reentry_strategy: str | None


def resolve_trade_mode_config(
    config: dict[str, Any],
    *,
    source: str,
    require_explicit_sidestep_reentry: bool = False,
) -> TradeModeConfigState:
    """Resolve trade-mode state from the canonical `trade_mode` config field."""
    trade_mode = (
        _optional_string(config.get("trade_mode")) or TradeMode.DYNAMIC_DCA.value
    )
    if trade_mode not in {
        TradeMode.DYNAMIC_DCA.value,
        TradeMode.SIDESTEP.value,
    }:
        raise build_invalid_trade_mode_error(
            source=source,
            message=f"Unsupported trade_mode '{trade_mode}'.",
            safe_fields={"trade_mode": trade_mode},
        )

    explicit_reentry_strategy = _optional_string(
        config.get("sidestep_reentry_strategy")
    )
    effective_reentry_strategy = explicit_reentry_strategy
    if effective_reentry_strategy is None:
        effective_reentry_strategy = _optional_string(config.get("dca_strategy"))

    if (
        require_explicit_sidestep_reentry
        and trade_mode == TradeMode.SIDESTEP.value
        and explicit_reentry_strategy is None
    ):
        raise build_missing_sidestep_reentry_strategy_error(
            source=source,
            safe_fields={
                "trade_mode": trade_mode,
                "sidestep_reentry_strategy": explicit_reentry_strategy,
                "dca_strategy": _optional_string(config.get("dca_strategy")),
            },
        )

    return TradeModeConfigState(
        trade_mode=trade_mode,
        lifecycle_mode=(
            TradeLifecycleMode.SIDESTEP_REENTRY.value
            if trade_mode == TradeMode.SIDESTEP.value
            else TradeLifecycleMode.CLASSIC_DCA.value
        ),
        dynamic_dca_enabled=trade_mode == TradeMode.DYNAMIC_DCA.value,
        sidestep_enabled=trade_mode == TradeMode.SIDESTEP.value,
        market=_optional_string(config.get("market")) or "spot",
        explicit_reentry_strategy=explicit_reentry_strategy,
        effective_reentry_strategy=effective_reentry_strategy,
    )


def normalize_trade_mode(config: dict[str, Any]) -> str:
    """Return the canonical trade mode for current config rows."""
    return resolve_trade_mode_config(config, source="runtime").trade_mode


def is_dynamic_dca_enabled(config: dict[str, Any]) -> bool:
    """Return whether runtime math should treat the config as dynamic DCA."""
    return normalize_trade_mode(config) == TradeMode.DYNAMIC_DCA.value


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

    trade_mode: str
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
        trade_mode_state = resolve_trade_mode_config(config, source="runtime")

        return cls(
            trade_mode=trade_mode_state.trade_mode,
            mode=trade_mode_state.lifecycle_mode,
            market=trade_mode_state.market,
            enabled=trade_mode_state.sidestep_enabled,
            bearish_exit_strategy=_optional_string(
                config.get("sidestep_bearish_strategy")
            ),
            reentry_strategy=trade_mode_state.effective_reentry_strategy,
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
        return self.enabled and self.market == "spot"
