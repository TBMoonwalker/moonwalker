import types

import model
import pytest
import service.signal_runtime as signal_runtime_module
from service.autopilot_memory import SymbolAdmissionProfile
from service.signal_runtime import (
    build_common_runtime_settings,
    is_max_bots_reached,
    parse_signal_settings,
    resolve_max_bots_log_interval,
    resolve_signal_admission_batch,
    resolve_signal_entry_orders,
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


class _DummyMemoryService:
    def __init__(self, profiles: dict[str, SymbolAdmissionProfile]) -> None:
        self._profiles = profiles

    def build_admission_profiles(
        self,
        symbols: list[str],
        *,
        enabled: bool,
    ) -> dict[str, SymbolAdmissionProfile]:
        assert enabled is True
        return {
            symbol: self._profiles[symbol]
            for symbol in symbols
            if symbol in self._profiles
        }


@pytest.fixture(autouse=True)
def _clear_signal_runtime_reservations() -> None:
    signal_runtime_module._PENDING_ADMISSION_SYMBOLS.clear()


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


@pytest.mark.asyncio
async def test_resolve_signal_admission_batch_prefers_favored_symbol(
    monkeypatch,
) -> None:
    _DummyOpenTradesModel.rows = [
        {"symbol": "ADA/USDT", "unsellable_amount": 0.0, "unsellable_reason": None},
    ]
    monkeypatch.setattr(model, "OpenTrades", _DummyOpenTradesModel)

    async def fake_memory_instance():
        return _DummyMemoryService(
            {
                "BTC/USDT": SymbolAdmissionProfile(
                    symbol="BTC/USDT",
                    memory_status="fresh",
                    trust_direction="favored",
                    trust_score=82.0,
                    reason_code="quick_profitable_closes",
                    uses_trust_ranking=True,
                ),
                "ETH/USDT": SymbolAdmissionProfile(
                    symbol="ETH/USDT",
                    memory_status="fresh",
                    trust_direction="neutral",
                    trust_score=51.0,
                    reason_code=None,
                    uses_trust_ranking=True,
                ),
            }
        )

    monkeypatch.setattr(
        signal_runtime_module.AutopilotMemoryService,
        "instance",
        staticmethod(fake_memory_instance),
    )

    batch = await resolve_signal_admission_batch(
        {"max_bots": 2, "autopilot": True},
        types.SimpleNamespace(
            get_profit=_async_result({"autopilot_effective_max_bots": 2})
        ),
        types.SimpleNamespace(resolve_runtime_state=_async_result({})),
        ["ETH/USDT", "BTC/USDT"],
    )

    assert batch.admitted_symbols == ["BTC/USDT"]
    decisions = {decision.symbol: decision for decision in batch.decisions}
    assert decisions["BTC/USDT"].reason_code == "admitted_trust_priority"
    assert decisions["BTC/USDT"].trust_direction == "favored"
    assert decisions["ETH/USDT"].reason_code == "skipped_ranked_out"
    assert decisions["ETH/USDT"].memory_status == "fresh"
    await batch.release()


@pytest.mark.asyncio
async def test_resolve_signal_admission_batch_falls_back_to_symbol_order_when_memory_is_not_fresh(
    monkeypatch,
) -> None:
    _DummyOpenTradesModel.rows = [
        {"symbol": "ADA/USDT", "unsellable_amount": 0.0, "unsellable_reason": None},
    ]
    monkeypatch.setattr(model, "OpenTrades", _DummyOpenTradesModel)

    async def fake_memory_instance():
        return _DummyMemoryService(
            {
                "BTC/USDT": SymbolAdmissionProfile(
                    symbol="BTC/USDT",
                    memory_status="warming_up",
                    trust_direction="neutral",
                    trust_score=67.0,
                    reason_code=None,
                    uses_trust_ranking=False,
                ),
                "SOL/USDT": SymbolAdmissionProfile(
                    symbol="SOL/USDT",
                    memory_status="warming_up",
                    trust_direction="neutral",
                    trust_score=91.0,
                    reason_code=None,
                    uses_trust_ranking=False,
                ),
            }
        )

    monkeypatch.setattr(
        signal_runtime_module.AutopilotMemoryService,
        "instance",
        staticmethod(fake_memory_instance),
    )

    batch = await resolve_signal_admission_batch(
        {"max_bots": 2, "autopilot": True},
        types.SimpleNamespace(
            get_profit=_async_result({"autopilot_effective_max_bots": 2})
        ),
        types.SimpleNamespace(resolve_runtime_state=_async_result({})),
        ["SOL/USDT", "BTC/USDT"],
    )

    assert batch.admitted_symbols == ["BTC/USDT"]
    decisions = {decision.symbol: decision for decision in batch.decisions}
    assert decisions["BTC/USDT"].reason_code == "admitted_fallback_order"
    assert decisions["BTC/USDT"].memory_status == "warming_up"
    assert decisions["SOL/USDT"].reason_code == "skipped_ranked_out"
    await batch.release()


@pytest.mark.asyncio
async def test_resolve_signal_admission_batch_respects_pending_reservations(
    monkeypatch,
) -> None:
    _DummyOpenTradesModel.rows = []
    monkeypatch.setattr(model, "OpenTrades", _DummyOpenTradesModel)

    async def fake_memory_instance():
        return _DummyMemoryService(
            {
                "BTC/USDT": SymbolAdmissionProfile(
                    symbol="BTC/USDT",
                    memory_status="fresh",
                    trust_direction="neutral",
                    trust_score=50.0,
                    reason_code=None,
                    uses_trust_ranking=True,
                ),
                "ETH/USDT": SymbolAdmissionProfile(
                    symbol="ETH/USDT",
                    memory_status="fresh",
                    trust_direction="neutral",
                    trust_score=50.0,
                    reason_code=None,
                    uses_trust_ranking=True,
                ),
            }
        )

    monkeypatch.setattr(
        signal_runtime_module.AutopilotMemoryService,
        "instance",
        staticmethod(fake_memory_instance),
    )

    first_batch = await resolve_signal_admission_batch(
        {"max_bots": 1, "autopilot": True},
        types.SimpleNamespace(
            get_profit=_async_result({"autopilot_effective_max_bots": 1})
        ),
        types.SimpleNamespace(resolve_runtime_state=_async_result({})),
        ["BTC/USDT"],
    )
    second_batch = await resolve_signal_admission_batch(
        {"max_bots": 1, "autopilot": True},
        types.SimpleNamespace(
            get_profit=_async_result({"autopilot_effective_max_bots": 1})
        ),
        types.SimpleNamespace(resolve_runtime_state=_async_result({})),
        ["ETH/USDT"],
    )

    assert first_batch.admitted_symbols == ["BTC/USDT"]
    assert second_batch.admitted_symbols == []
    assert second_batch.decisions[0].reason_code == "skipped_capacity_full"

    await first_batch.release()

    third_batch = await resolve_signal_admission_batch(
        {"max_bots": 1, "autopilot": True},
        types.SimpleNamespace(
            get_profit=_async_result({"autopilot_effective_max_bots": 1})
        ),
        types.SimpleNamespace(resolve_runtime_state=_async_result({})),
        ["ETH/USDT"],
    )

    assert third_batch.admitted_symbols == ["ETH/USDT"]
    await third_batch.release()


@pytest.mark.asyncio
async def test_resolve_signal_entry_orders_reuses_shared_autopilot_policy() -> None:
    statistic = types.SimpleNamespace(
        get_profit=_async_result({"funds_locked": 42.0}),
    )
    autopilot = types.SimpleNamespace(
        resolve_runtime_state=_async_result(
            {
                "mode": "low",
                "effective_max_bots": 2,
                "green_phase_active": False,
                "green_phase_extra_deals": 0,
                "memory_status": "fresh",
            }
        ),
        resolve_trading_policy=_async_result(
            types.SimpleNamespace(
                baseline_base_order=100.0,
                suggested_base_order=115.0,
                entry_order_size=115.0,
                adaptive_entry_size_applied=True,
                adaptive_entry_reason_code="quick_profitable_closes",
                adaptive_trust_direction="favored",
                adaptive_trust_score=72.0,
                memory_status="fresh",
            )
        ),
    )

    decisions = await resolve_signal_entry_orders(
        {
            "autopilot": True,
            "bo": 100.0,
            "timeframe": "15m",
        },
        statistic,
        autopilot,
        ["BTC/USDT"],
        signal_name="asap",
        strategy_name="ema_cross",
        timeframe="15m",
    )

    decision = decisions["BTC/USDT"]
    assert decision.order_size == 115.0
    assert decision.baseline_order_size == 100.0
    assert decision.entry_size_applied is True
    assert decision.reason_code == "quick_profitable_closes"
    assert '"resolved_order_size": 115.0' in decision.metadata_json


def _async_result(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner


@pytest.mark.asyncio
async def test_resolve_signal_admission_batch_blocks_waiting_campaign_reentry(
    monkeypatch,
) -> None:
    _DummyOpenTradesModel.rows = []
    monkeypatch.setattr(model, "OpenTrades", _DummyOpenTradesModel)

    class _DummyCampaignService:
        async def get_admission_blocks(self, _symbols: list[str]):
            return {
                "BTC/USDT": signal_runtime_module.CampaignAdmissionBlock(
                    symbol="BTC/USDT",
                    campaign_id="campaign-1",
                    state="flat_waiting_reentry",
                    reason_code="skipped_campaign_waiting_reentry",
                )
            }

    async def fake_memory_instance():
        return _DummyMemoryService(
            {
                "BTC/USDT": SymbolAdmissionProfile(
                    symbol="BTC/USDT",
                    memory_status="fresh",
                    trust_direction="favored",
                    trust_score=80.0,
                    reason_code=None,
                    uses_trust_ranking=True,
                ),
            }
        )

    monkeypatch.setattr(
        signal_runtime_module.AutopilotMemoryService,
        "instance",
        staticmethod(fake_memory_instance),
    )
    monkeypatch.setattr(
        signal_runtime_module.SpotSidestepCampaignService,
        "instance",
        staticmethod(_async_result(_DummyCampaignService())),
    )

    batch = await resolve_signal_admission_batch(
        {"max_bots": 2, "autopilot": True},
        types.SimpleNamespace(
            get_profit=_async_result({"autopilot_effective_max_bots": 2})
        ),
        types.SimpleNamespace(resolve_runtime_state=_async_result({})),
        ["BTC/USDT"],
    )

    assert batch.admitted_symbols == []
    assert batch.decisions[0].reason_code == "skipped_campaign_waiting_reentry"
