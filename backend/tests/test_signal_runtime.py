from service.signal_runtime import (
    build_common_runtime_settings,
    parse_signal_settings,
    resolve_max_bots_log_interval,
)


def test_parse_signal_settings_accepts_json_and_dict() -> None:
    assert parse_signal_settings({"api_key": "x"}) == {"api_key": "x"}
    assert parse_signal_settings('{"api_key":"x"}') == {"api_key": "x"}


def test_build_common_runtime_settings_parses_shared_filters() -> None:
    runtime = build_common_runtime_settings(
        {
            "pair_denylist": "btc/usdt, eth/usdt",
            "pair_allowlist": "BTC/USDT,ETH/USDT",
            "volume": '{"size": 5, "range": "M"}',
            "timeframe": "15m",
        }
    )

    assert runtime.pair_denylist == ["BTC", "ETH"]
    assert runtime.pair_allowlist == ["BTC/USDT", "ETH/USDT"]
    assert runtime.volume == {"size": 5, "range": "M"}
    assert runtime.strategy_timeframe == "15m"


def test_build_common_runtime_settings_treats_false_string_lists_as_empty() -> None:
    runtime = build_common_runtime_settings(
        {
            "pair_denylist": False,
            "pair_allowlist": "false",
            "timeframe": "1m",
        }
    )

    assert runtime.pair_denylist is None
    assert runtime.pair_allowlist is None


def test_resolve_max_bots_log_interval_clamps_invalid_values() -> None:
    assert resolve_max_bots_log_interval({"max_bots_log_interval_sec": "0"}) == 1.0
    assert resolve_max_bots_log_interval({"max_bots_log_interval_sec": "bad"}) == 60.0
