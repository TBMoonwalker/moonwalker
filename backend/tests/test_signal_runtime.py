import types

import model
import pytest
from service.signal_runtime import (
    build_common_runtime_settings,
    is_max_bots_reached,
    parse_signal_settings,
    resolve_max_bots_log_interval,
)


def test_parse_signal_settings_accepts_json_and_dict() -> None:
    assert parse_signal_settings({"api_key": "x"}) == {"api_key": "x"}
    assert parse_signal_settings('{"api_key":"x"}') == {"api_key": "x"}


def test_parse_signal_settings_rejects_removed_python_literal_fallback() -> None:
    with pytest.raises(ValueError):
        parse_signal_settings("{'api_key': 'x'}")


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


class _DummyOpenTradesModel:
    rows = []

    @classmethod
    def all(cls):
        return cls()

    async def values(self, *_args, **_kwargs):
        return list(self.rows)


@pytest.mark.asyncio
async def test_is_max_bots_reached_prefers_effective_autopilot_limit(
    monkeypatch,
) -> None:
    _DummyOpenTradesModel.rows = [
        {"symbol": "BTC/USDT", "unsellable_amount": 0.0, "unsellable_reason": None},
        {"symbol": "ETH/USDT", "unsellable_amount": 0.0, "unsellable_reason": None},
    ]
    monkeypatch.setattr(model, "OpenTrades", _DummyOpenTradesModel)

    statistic = types.SimpleNamespace(
        get_profit=_async_result(
            {
                "funds_locked": 120.0,
                "autopilot_effective_max_bots": 1,
            }
        )
    )
    autopilot = types.SimpleNamespace(resolve_runtime_state=_async_result({}))

    blocked = await is_max_bots_reached(
        {"max_bots": 5},
        statistic,
        autopilot,
    )

    assert blocked is True


@pytest.mark.asyncio
async def test_is_max_bots_reached_uses_active_open_trade_count(
    monkeypatch,
) -> None:
    _DummyOpenTradesModel.rows = [
        {"symbol": "BTC/USDT", "unsellable_amount": 0.0, "unsellable_reason": None},
        {"symbol": "ETH/USDT", "unsellable_amount": 0.0, "unsellable_reason": None},
        {"symbol": "SOL/USDT", "unsellable_amount": 0.0, "unsellable_reason": None},
    ]
    monkeypatch.setattr(model, "OpenTrades", _DummyOpenTradesModel)

    statistic = types.SimpleNamespace(get_profit=_async_result({}))
    autopilot = types.SimpleNamespace(resolve_runtime_state=_async_result({}))

    blocked = await is_max_bots_reached(
        {"max_bots": 2},
        statistic,
        autopilot,
    )

    assert blocked is True


@pytest.mark.asyncio
async def test_is_max_bots_reached_ignores_unsellable_open_trade_rows(
    monkeypatch,
) -> None:
    _DummyOpenTradesModel.rows = [
        {"symbol": "BTC/USDT", "unsellable_amount": 0.0, "unsellable_reason": None},
        {
            "symbol": "ETH/USDT",
            "unsellable_amount": 0.42,
            "unsellable_reason": "minimum_notional",
        },
    ]
    monkeypatch.setattr(model, "OpenTrades", _DummyOpenTradesModel)

    statistic = types.SimpleNamespace(get_profit=_async_result({}))
    autopilot = types.SimpleNamespace(resolve_runtime_state=_async_result({}))

    blocked = await is_max_bots_reached(
        {"max_bots": 2},
        statistic,
        autopilot,
    )

    assert blocked is False


def _async_result(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner
