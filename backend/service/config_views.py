"""Typed runtime views derived from the dynamic config snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from service.config import resolve_timeframe


def _optional_string(value: Any) -> str | None:
    """Normalize optional config strings with whitespace trimming."""
    normalized = str(value or "").strip()
    return normalized or None


def _float_config_value(
    config: dict[str, Any],
    key: str,
    *,
    default: float,
    falsey_fallback: float,
) -> float:
    """Normalize a float-like config value with explicit fallback semantics."""
    try:
        return float(config.get(key, default) or falsey_fallback)
    except (TypeError, ValueError):
        return falsey_fallback


def _int_config_value(
    config: dict[str, Any],
    key: str,
    *,
    default: int,
    falsey_fallback: int,
) -> int:
    """Normalize an int-like config value with explicit fallback semantics."""
    try:
        return int(config.get(key, default) or falsey_fallback)
    except (TypeError, ValueError):
        return falsey_fallback


def _float_config_default_only(value: Any, *, default: float) -> float:
    """Normalize a float-like config value while preserving explicit zero values."""
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return default


def _int_config_default_only(value: Any, *, default: int) -> int:
    """Normalize an int-like config value while preserving explicit zero values."""
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ExchangeConnectionConfigView:
    """Typed exchange client connection settings derived from config."""

    exchange: str | None
    key: str | None
    secret: str | None
    market: str
    dry_run: bool
    sandbox: bool
    exchange_hostname: str | None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "ExchangeConnectionConfigView":
        """Build normalized exchange connection settings from the raw config."""
        dry_run = bool(config.get("dry_run", True))
        return cls(
            exchange=_optional_string(config.get("exchange")),
            key=_optional_string(config.get("key")),
            secret=_optional_string(config.get("secret")),
            market=_optional_string(config.get("market")) or "spot",
            dry_run=dry_run,
            sandbox=False if dry_run else bool(config.get("sandbox", False)),
            exchange_hostname=_optional_string(config.get("exchange_hostname")),
        )

    def to_runtime_dict(self) -> dict[str, Any]:
        """Return the normalized config fields that control exchange lifecycles."""
        return {
            "exchange": self.exchange,
            "key": self.key,
            "secret": self.secret,
            "market": self.market,
            "dry_run": self.dry_run,
            "sandbox": self.sandbox,
            "exchange_hostname": self.exchange_hostname,
        }


@dataclass(frozen=True)
class SignalPluginConfigView:
    """Typed signal-plugin selection derived from the config snapshot."""

    signal_name: str | None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SignalPluginConfigView":
        """Build a typed signal-plugin selection from the raw config snapshot."""
        return cls(signal_name=_optional_string(config.get("signal")))


@dataclass(frozen=True)
class WatcherRuntimeConfigView:
    """Typed watcher runtime settings derived from the config snapshot."""

    watcher_ohlcv: bool
    btc_pulse_enabled: bool
    timeframe: str
    exchange_connection: ExchangeConnectionConfigView

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "WatcherRuntimeConfigView":
        """Build normalized watcher settings from the raw config snapshot."""
        return cls(
            watcher_ohlcv=bool(config.get("watcher_ohlcv", True)),
            btc_pulse_enabled=bool(config.get("btc_pulse", False)),
            timeframe=resolve_timeframe(config),
            exchange_connection=ExchangeConnectionConfigView.from_config(config),
        )


@dataclass(frozen=True)
class DcaRuntimeConfigView:
    """Typed DCA runtime settings derived from the config snapshot."""

    tp_spike_confirm_enabled: bool
    tp_spike_confirm_seconds: float
    tp_spike_confirm_ticks: int
    dca_strategy: str | None
    tp_strategy: str | None
    dca_enabled: bool
    take_profit: float
    stop_loss: float
    trailing_tp: float
    max_safety_orders: int
    dynamic_dca: bool
    safety_order_volume_scale: float
    step_scale: float
    safety_order_step_percentage: float
    safety_order_size: float
    base_order_amount: float
    dynamic_dca_ath_cache_ttl: int
    atr_timeframe: str
    atr_length: int
    atr_regime_low_k: float
    atr_regime_mid_k: float
    atr_regime_high_k: float
    trade_safety_order_budget_ratio: float

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "DcaRuntimeConfigView":
        """Build normalized DCA settings from the raw config snapshot."""
        atr_timeframe = str(
            config.get(
                "dynamic_so_atr_timeframe",
                config.get("dynamic_dca_ath_timeframe", "1h"),
            )
            or "1h"
        ).strip()
        return cls(
            tp_spike_confirm_enabled=bool(
                config.get("tp_spike_confirm_enabled", False)
            ),
            tp_spike_confirm_seconds=max(
                0.0,
                _float_config_value(
                    config,
                    "tp_spike_confirm_seconds",
                    default=3.0,
                    falsey_fallback=0.0,
                ),
            ),
            tp_spike_confirm_ticks=max(
                0,
                _int_config_value(
                    config,
                    "tp_spike_confirm_ticks",
                    default=0,
                    falsey_fallback=0,
                ),
            ),
            dca_strategy=_optional_string(config.get("dca_strategy")),
            tp_strategy=_optional_string(config.get("tp_strategy")),
            dca_enabled=bool(config.get("dca", False)),
            take_profit=_float_config_default_only(
                config.get("tp", 10000.0),
                default=10000.0,
            ),
            stop_loss=_float_config_default_only(
                config.get("sl", 10000.0),
                default=10000.0,
            ),
            trailing_tp=_float_config_value(
                config,
                "trailing_tp",
                default=0.0,
                falsey_fallback=0.0,
            ),
            max_safety_orders=_int_config_value(
                config,
                "mstc",
                default=0,
                falsey_fallback=0,
            ),
            dynamic_dca=bool(config.get("dynamic_dca", False)),
            safety_order_volume_scale=_float_config_value(
                config,
                "os",
                default=1.0,
                falsey_fallback=1.0,
            ),
            step_scale=_float_config_value(
                config,
                "ss",
                default=0.0,
                falsey_fallback=0.0,
            ),
            safety_order_step_percentage=_float_config_value(
                config,
                "sos",
                default=0.0,
                falsey_fallback=0.0,
            ),
            safety_order_size=_float_config_value(
                config,
                "so",
                default=0.0,
                falsey_fallback=0.0,
            ),
            base_order_amount=_float_config_value(
                config,
                "bo",
                default=0.0,
                falsey_fallback=0.0,
            ),
            dynamic_dca_ath_cache_ttl=_int_config_default_only(
                config.get("dynamic_dca_ath_cache_ttl", 60),
                default=60,
            ),
            atr_timeframe=atr_timeframe or "1h",
            atr_length=_int_config_value(
                config,
                "dynamic_so_atr_length",
                default=14,
                falsey_fallback=14,
            ),
            atr_regime_low_k=_float_config_value(
                config,
                "dynamic_so_atr_regime_low_k",
                default=2.2,
                falsey_fallback=2.2,
            ),
            atr_regime_mid_k=_float_config_value(
                config,
                "dynamic_so_atr_regime_mid_k",
                default=1.8,
                falsey_fallback=1.8,
            ),
            atr_regime_high_k=_float_config_value(
                config,
                "dynamic_so_atr_regime_high_k",
                default=1.4,
                falsey_fallback=1.4,
            ),
            trade_safety_order_budget_ratio=_float_config_value(
                config,
                "trade_safety_order_budget_ratio",
                default=0.95,
                falsey_fallback=0.95,
            ),
        )
