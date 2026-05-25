from service.strategy_capability import (
    filter_supported_strategies,
    get_configured_strategy_history_lookback_days,
    get_configured_strategy_min_history_candles,
    get_strategy_min_history_candles,
    get_strategy_support_error,
)


def test_supported_strategy_has_no_support_error() -> None:
    assert get_strategy_support_error("ema20_swing") is None
    assert get_strategy_support_error("ema20_swing_reverse") is None
    assert get_strategy_support_error("ema_swing_reverse") is None
    assert get_strategy_support_error("bollinger_buy") is None
    assert get_strategy_support_error("bollinger_sell") is None


def test_unsupported_strategy_reports_missing_indicator_methods() -> None:
    error = get_strategy_support_error("unknown_strategy")
    assert error is not None
    assert "not registered" in error


def test_filter_supported_strategies_removes_unsupported_entries() -> None:
    supported = filter_supported_strategies(
        [
            "ema_down",
            "ema20_swing",
            "ema20_swing_reverse",
            "ema_swing_reverse",
            "unknown_strategy",
        ]
    )
    assert "ema_down" in supported
    assert "ema20_swing" in supported
    assert "ema20_swing_reverse" in supported
    assert "ema_swing_reverse" not in supported
    assert "unknown_strategy" not in supported


def test_get_strategy_min_history_candles_returns_expected_warmup() -> None:
    assert get_strategy_min_history_candles("ema_down") == 200
    assert get_strategy_min_history_candles("ema20_swing") == 200
    assert get_strategy_min_history_candles("ema20_swing_reverse") == 200
    assert get_strategy_min_history_candles("ema_low") == 200
    assert get_strategy_min_history_candles("ema_swing_reverse") == 200
    assert get_strategy_min_history_candles("bollinger_buy") == 202
    assert get_strategy_min_history_candles("bollinger_sell") == 50
    assert get_strategy_min_history_candles(None) == 0


def test_get_configured_strategy_min_history_candles_uses_maximum_requirement() -> None:
    required = get_configured_strategy_min_history_candles(
        {
            "signal_strategy": "ema20_swing",
            "dca_strategy": "ema_low",
            "tp_strategy": "ema_down",
        }
    )
    assert required == 200


def test_get_configured_strategy_min_history_candles_uses_sidestep_mode_strategies() -> (
    None
):
    required = get_configured_strategy_min_history_candles(
        {
            "trade_lifecycle_mode": "sidestep_reentry",
            "market": "spot",
            "sidestep_bearish_strategy": "ema_down",
            "sidestep_reentry_strategy": "ema20_swing_reverse",
            "dca_strategy": "ema20_swing",
            "tp_strategy": "ema_down",
        }
    )
    assert required == 200


def test_get_configured_strategy_min_history_candles_respects_canonical_mode_over_legacy_flag() -> (
    None
):
    required = get_configured_strategy_min_history_candles(
        {
            "trade_mode": "dynamic_dca",
            "trade_lifecycle_mode": "classic_dca",
            "dynamic_dca": True,
            "sidestep_campaign_enabled": True,
            "market": "spot",
            "sidestep_bearish_strategy": "ema_down",
            "sidestep_reentry_strategy": "ema20_swing_reverse",
            "dca_strategy": "ema20_swing",
            "tp_strategy": "ema_down",
        }
    )
    assert required == 200


def test_get_configured_strategy_history_lookback_days_respects_timeframe() -> None:
    required_days = get_configured_strategy_history_lookback_days(
        {"signal_strategy": "ema_low"},
        "1h",
    )
    assert required_days == 17


def test_get_configured_strategy_history_lookback_days_uses_sidestep_mode_strategies() -> (
    None
):
    required_days = get_configured_strategy_history_lookback_days(
        {
            "trade_lifecycle_mode": "sidestep_reentry",
            "market": "spot",
            "sidestep_bearish_strategy": "ema_down",
            "sidestep_reentry_strategy": "ema20_swing_reverse",
            "dca_strategy": "ema20_swing",
        },
        "1h",
        include_signal_strategy=False,
    )
    assert required_days == 17
