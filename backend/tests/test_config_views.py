from service.config_views import (
    DcaRuntimeConfigView,
    ExchangeConnectionConfigView,
    SignalPluginConfigView,
    WatcherRuntimeConfigView,
)


def test_exchange_connection_config_view_normalizes_dry_run_and_strings() -> None:
    config = ExchangeConnectionConfigView.from_config(
        {
            "exchange": "  binance  ",
            "key": "  key  ",
            "secret": "secret",
            "market": "",
            "dry_run": True,
            "sandbox": True,
            "exchange_hostname": "  api.exchange.test  ",
        }
    )

    assert config.exchange == "binance"
    assert config.key == "key"
    assert config.secret == "secret"
    assert config.market == "spot"
    assert config.dry_run is True
    assert config.sandbox is False
    assert config.exchange_hostname == "api.exchange.test"


def test_signal_plugin_config_view_normalizes_blank_signal_name() -> None:
    assert SignalPluginConfigView.from_config({"signal": ""}).signal_name is None
    assert (
        SignalPluginConfigView.from_config({"signal": "  asap  "}).signal_name == "asap"
    )


def test_watcher_runtime_config_view_reuses_exchange_connection_settings() -> None:
    config = WatcherRuntimeConfigView.from_config(
        {
            "watcher_ohlcv": False,
            "btc_pulse": True,
            "timeframe": " 15m ",
            "exchange": "  binance  ",
            "market": "",
            "dry_run": True,
            "sandbox": True,
            "exchange_hostname": " demo.exchange.test ",
        }
    )

    assert config.watcher_ohlcv is False
    assert config.btc_pulse_enabled is True
    assert config.timeframe == "15m"
    assert config.exchange_connection.exchange == "binance"
    assert config.exchange_connection.market == "spot"
    assert config.exchange_connection.dry_run is True
    assert config.exchange_connection.sandbox is False
    assert config.exchange_connection.exchange_hostname == "demo.exchange.test"


def test_dca_runtime_config_view_applies_tp_confirmation_defaults() -> None:
    config = DcaRuntimeConfigView.from_config({})

    assert config.tp_spike_confirm_enabled is False
    assert config.tp_spike_confirm_seconds == 3.0
    assert config.tp_spike_confirm_ticks == 0
    assert config.tp_limit_prearm_enabled is False
    assert config.tp_limit_prearm_margin_percent == 0.25
    assert config.dca_strategy is None
    assert config.tp_strategy is None
    assert config.dca_enabled is False
    assert config.take_profit == 10000.0
    assert config.stop_loss == 10000.0
    assert config.trailing_tp == 0.0
    assert config.max_safety_orders == 0
    assert config.dynamic_dca is False
    assert config.safety_order_volume_scale == 1.0
    assert config.step_scale == 0.0
    assert config.safety_order_step_percentage == 0.0
    assert config.safety_order_size == 0.0
    assert config.base_order_amount == 0.0
    assert config.dynamic_dca_ath_cache_ttl == 60
    assert config.atr_timeframe == "1h"
    assert config.atr_length == 14
    assert config.atr_regime_low_k == 2.2
    assert config.atr_regime_mid_k == 1.8
    assert config.atr_regime_high_k == 1.4
    assert config.trade_safety_order_budget_ratio == 0.95


def test_dca_runtime_config_view_normalizes_dynamic_dca_fields() -> None:
    config = DcaRuntimeConfigView.from_config(
        {
            "tp_spike_confirm_enabled": True,
            "tp_spike_confirm_seconds": "4.5",
            "tp_spike_confirm_ticks": "2",
            "tp_limit_prearm_enabled": True,
            "tp_limit_prearm_margin_percent": "0.75",
            "dca_strategy": "  ema_swing  ",
            "tp_strategy": "  ema_down  ",
            "dca": True,
            "tp": "2.5",
            "sl": "6.0",
            "trailing_tp": "1.25",
            "mstc": "5",
            "dynamic_dca": True,
            "os": "1.5",
            "ss": "0.8",
            "sos": "2.5",
            "so": "150",
            "bo": "100",
            "dynamic_dca_ath_cache_ttl": "120",
            "dynamic_dca_ath_timeframe": "4h",
            "dynamic_so_atr_length": "21",
            "dynamic_so_atr_regime_low_k": "2.8",
            "dynamic_so_atr_regime_mid_k": "2.0",
            "dynamic_so_atr_regime_high_k": "1.6",
            "trade_safety_order_budget_ratio": "0.6",
        }
    )

    assert config.tp_spike_confirm_enabled is True
    assert config.tp_spike_confirm_seconds == 4.5
    assert config.tp_spike_confirm_ticks == 2
    assert config.tp_limit_prearm_enabled is True
    assert config.tp_limit_prearm_margin_percent == 0.75
    assert config.dca_strategy == "ema_swing"
    assert config.tp_strategy == "ema_down"
    assert config.dca_enabled is True
    assert config.take_profit == 2.5
    assert config.stop_loss == 6.0
    assert config.trailing_tp == 1.25
    assert config.max_safety_orders == 5
    assert config.dynamic_dca is True
    assert config.safety_order_volume_scale == 1.5
    assert config.step_scale == 0.8
    assert config.safety_order_step_percentage == 2.5
    assert config.safety_order_size == 150.0
    assert config.base_order_amount == 100.0
    assert config.dynamic_dca_ath_cache_ttl == 120
    assert config.atr_timeframe == "4h"
    assert config.atr_length == 21
    assert config.atr_regime_low_k == 2.8
    assert config.atr_regime_mid_k == 2.0
    assert config.atr_regime_high_k == 1.6
    assert config.trade_safety_order_budget_ratio == 0.6


def test_dca_runtime_config_view_preserves_explicit_zero_values() -> None:
    config = DcaRuntimeConfigView.from_config(
        {
            "tp": 0,
            "sl": 0,
            "dynamic_dca_ath_cache_ttl": 0,
        }
    )

    assert config.take_profit == 0.0
    assert config.stop_loss == 0.0
    assert config.dynamic_dca_ath_cache_ttl == 0
