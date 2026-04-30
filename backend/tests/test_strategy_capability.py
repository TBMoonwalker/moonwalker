from service.strategy_capability import (
    filter_supported_strategies,
    get_configured_strategy_history_lookback_days,
    get_configured_strategy_min_history_candles,
    get_strategy_min_history_candles,
    get_strategy_support_error,
)


def test_supported_strategy_has_no_support_error() -> None:
    assert get_strategy_support_error("ema_cross") is None
    assert get_strategy_support_error("ema_swing_reverse") is None


def test_unsupported_strategy_reports_missing_indicator_methods() -> None:
    error = get_strategy_support_error("bbands_cross")
    assert error is not None
    assert "calculate_bbands_cross" in error


def test_filter_supported_strategies_removes_unsupported_entries() -> None:
    supported = filter_supported_strategies(
        ["ema_cross", "bbands_cross", "ichimoku_cross"]
    )
    assert "ema_cross" in supported
    assert "bbands_cross" not in supported
    assert "ichimoku_cross" not in supported


def test_get_strategy_min_history_candles_returns_expected_warmup() -> None:
    assert get_strategy_min_history_candles("ema_cross") == 22
    assert get_strategy_min_history_candles("ema_low") == 200
    assert get_strategy_min_history_candles("ema_swing_reverse") == 200
    assert get_strategy_min_history_candles(None) == 0


def test_get_configured_strategy_min_history_candles_uses_maximum_requirement() -> None:
    required = get_configured_strategy_min_history_candles(
        {
            "signal_strategy": "ema_cross",
            "dca_strategy": "ema_low",
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
