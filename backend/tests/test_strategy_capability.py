from service.strategy_capability import (
    filter_supported_strategies,
    get_strategy_support_error,
)


def test_supported_strategy_has_no_support_error():
    assert get_strategy_support_error("ema_cross") is None


def test_unsupported_strategy_reports_missing_indicator_methods():
    error = get_strategy_support_error("bbands_cross")
    assert error is not None
    assert "calculate_bbands_cross" in error


def test_filter_supported_strategies_removes_unsupported_entries():
    supported = filter_supported_strategies(
        ["ema_cross", "bbands_cross", "ichimoku_cross"]
    )
    assert "ema_cross" in supported
    assert "bbands_cross" not in supported
    assert "ichimoku_cross" not in supported
