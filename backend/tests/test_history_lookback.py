import pytest
from service.config import (
    deserialize_config_value,
    parse_history_lookback_to_days,
    resolve_history_lookback_days,
)


def test_parse_history_lookback_to_days_supports_units() -> None:
    assert parse_history_lookback_to_days("30d") == 30
    assert parse_history_lookback_to_days("2w") == 14
    assert parse_history_lookback_to_days("6m") == 180
    assert parse_history_lookback_to_days("1y") == 365


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", None),
        ("false", None),
        ("30", 30),
        ("0", None),
        ("invalid", None),
        ("0d", None),
    ],
)
def test_parse_history_lookback_to_days_rejects_invalid_windows(
    value: str,
    expected: int | None,
) -> None:
    assert parse_history_lookback_to_days(value) == expected


@pytest.mark.parametrize(
    ("value", "value_type", "expected"),
    [
        (True, "int", 1),
        ("false", "int", 0),
        ("12", "int", 12),
        ("invalid", "int", 0),
        (False, "float", 0.0),
        ("null", "float", 0.0),
        ("12.5", "float", 12.5),
        ("invalid", "float", 0.0),
    ],
)
def test_deserialize_config_value_handles_legacy_numeric_forms(
    value: object,
    value_type: str,
    expected: int | float,
) -> None:
    assert deserialize_config_value(value, value_type) == expected


def test_resolve_history_lookback_days_prefers_new_key() -> None:
    config = {
        "history_lookback_time": "180d",
        "timeframe": "1m",
    }
    assert resolve_history_lookback_days(config) == 180


def test_resolve_history_lookback_days_ignores_removed_legacy_key() -> None:
    config = {
        "history_from_data": 45,
        "timeframe": "4h",
    }
    assert resolve_history_lookback_days(config) == 365


def test_resolve_history_lookback_days_uses_timeframe_defaults() -> None:
    assert resolve_history_lookback_days({"timeframe": "1m"}) == 30
    assert resolve_history_lookback_days({"timeframe": "15m"}) == 90
    assert resolve_history_lookback_days({"timeframe": "1h"}) == 180
    assert resolve_history_lookback_days({"timeframe": "4h"}) == 365
    assert resolve_history_lookback_days({"timeframe": "1d"}) == 1095
    assert resolve_history_lookback_days({"timeframe": "1w"}) == 1825
