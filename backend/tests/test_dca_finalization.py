"""Leaf unit tests for the pure helpers in service/dca/finalization.py.

Value: protects=entry-size retry reasons and retry payload, TP-limit
    fallback pricing and payload shape, and closed-trade partial arithmetic
    including zero partials.
fails_when=the retry reason set, fallback pricing, or partial totals change.
why_new=indirect full-flow coverage only; these helpers had no unit tests.
seam=none (collaborators are fakes; no exchange or database access).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import helper
import pytest
from service.dca import finalization
from service.dca.finalization import (
    build_entry_size_retry_order,
    build_tp_limit_sell_payload,
)
from service.dca.recovery_sizing import build_recovery_sizing_policy


@dataclass(frozen=True)
class _UnusedCollaborator:
    """Placeholder collaborator for context fields a helper never touches."""


def _dependencies(*, trades: Any = None, utils: Any = None) -> Any:
    """Build a finalization context with real utils and inert collaborators."""
    return finalization.DcaFinalizationContext(
        trades=trades or _UnusedCollaborator(),
        monitoring=_UnusedCollaborator(),
        placement_workflow=_UnusedCollaborator(),
        exchange=_UnusedCollaborator(),
        utils=utils or helper.Utils(),
    )


@pytest.mark.parametrize(
    "reason",
    sorted(finalization.ENTRY_SIZING_RETRY_REASONS),
)
def test_entry_size_retry_builds_baseline_order_for_each_fallback_reason(
    reason: str,
) -> None:
    order = {
        "baseorder": True,
        "safetyorder": False,
        "ordersize": 115.0,
        "baseline_order_size": 100.0,
        "entry_size_applied": True,
        "metadata_json": json.dumps({"entry_sizing": {"applied": True}}),
    }
    original = json.loads(json.dumps(order))

    retry = build_entry_size_retry_order(order, {"ok": False, "reason": reason})

    assert retry is not None
    assert retry["ordersize"] == 100.0
    assert retry["entry_size_applied"] is False
    assert retry["entry_size_fallback_applied"] is True
    assert retry["entry_size_fallback_reason"] == reason
    metadata = json.loads(retry["metadata_json"])
    assert metadata["entry_sizing"]["applied"] is False
    assert metadata["entry_sizing"]["fallback_applied"] is True
    assert metadata["entry_sizing"]["fallback_reason_code"] == reason
    assert metadata["entry_sizing"]["resolved_order_size"] == 100.0
    assert order == original, "retry must not mutate the incoming order"


@pytest.mark.parametrize(
    "order",
    [
        # Only base orders carry entry sizing.
        {
            "safetyorder": True,
            "ordersize": 115.0,
            "baseline_order_size": 100.0,
            "entry_size_applied": True,
        },
        # Entry sizing never applied, nothing to fall back.
        {"baseorder": True, "ordersize": 115.0, "baseline_order_size": 100.0},
        # Sizing applied but already at the baseline.
        {
            "baseorder": True,
            "ordersize": 100.0,
            "baseline_order_size": 100.0,
            "entry_size_applied": True,
        },
    ],
)
def test_entry_size_retry_gives_up_outside_the_contract(
    order: dict[str, Any],
) -> None:
    assert (
        build_entry_size_retry_order(
            order, {"ok": False, "reason": "invalid_price_or_amount"}
        )
        is None
    )
    assert build_entry_size_retry_order(order, None) is None


def test_entry_size_retry_rejects_unknown_fallback_reasons() -> None:
    order = {
        "baseorder": True,
        "ordersize": 115.0,
        "baseline_order_size": 100.0,
        "entry_size_applied": True,
    }
    assert build_entry_size_retry_order(order, {"ok": False, "reason": ""}) is None
    assert (
        build_entry_size_retry_order(order, {"ok": False, "reason": "unknown"}) is None
    )
    assert build_entry_size_retry_order(order, {"ok": True}) is None


def test_tp_limit_sell_payload_falls_back_to_trade_pricing() -> None:
    trades = {
        "symbol": "BTC/USDC",
        "tp_limit_order_id": "tp-1",
        "tp_limit_order_price": 110.0,
        "tp_limit_order_amount": 2.0,
        "sellable_amount": 2.5,
        "total_cost": 200.0,
        "total_amount": 2.5,
        "fee": 0.0,
        "current_price": 105.0,
    }
    # No exchange price evidence: price and amount must come from the trade.
    payload = build_tp_limit_sell_payload(
        trades, {"timestamp": 1700000000000}, dependencies=_dependencies()
    )

    assert payload["id"] == "tp-1"
    assert payload["symbol"] == "BTC/USDC"
    assert payload["side"] == "sell"
    assert payload["ordertype"] == "limit"
    assert payload["price"] == 110.0
    assert payload["amount"] == 2.0
    assert payload["total_amount"] == 2.0
    assert payload["requested_total_amount"] == 2.5
    assert payload["cost"] == 220.0
    assert payload["fee"] == 0.0
    assert payload["total_cost"] == 200.0
    # average buy 200 / 2.5 = 80 -> (110 - 80) / 80
    assert payload["actual_pnl"] == pytest.approx(37.5)


def test_tp_limit_sell_payload_prefers_exchange_evidence() -> None:
    trades = {
        "symbol": "BTC/USDC",
        "tp_limit_order_id": "tp-1",
        "tp_limit_order_price": 110.0,
        "tp_limit_order_amount": 2.0,
        "sellable_amount": 2.5,
        "total_cost": 200.0,
        "total_amount": 2.5,
        "fee": 0.0,
        "current_price": 105.0,
    }
    payload = build_tp_limit_sell_payload(
        trades,
        {"id": "exchange-tp", "average": 111.0, "filled": 1.5, "fee": 0.05},
        dependencies=_dependencies(),
    )

    assert payload["id"] == "exchange-tp"
    assert payload["price"] == 111.0
    assert payload["amount"] == 1.5
    assert payload["cost"] == pytest.approx(1.5 * 111.0)
    assert payload["fee"] == 0.05


class _StatsTradeReader:
    """Fake trade reader that refuses the second partial-total read."""

    def __init__(self) -> None:
        self.partial_reads = 0

    async def get_trade_by_ordertype(self, _symbol: str, **_kwargs: Any) -> Any:
        return [{"timestamp": 1700000000000.0}]

    async def get_open_trades_by_symbol(self, _symbol: str) -> Any:
        return [{"so_count": 2}]

    async def get_partial_sell_execution(self, *_args: Any, **_kwargs: Any) -> Any:
        self.partial_reads += 1
        raise AssertionError("supplied partial totals must not trigger a second read")


@pytest.mark.asyncio
async def test_closed_trade_stats_uses_supplied_partial_totals() -> None:
    trades = _StatsTradeReader()
    order_status: dict[str, Any] = {
        "symbol": "BTC/USDC",
        "total_cost": 200.0,
        "total_amount": 1.0,
        "price": 120.0,
        "timestamp": 1700000100000,
        "close_reason": "take_profit",
    }

    result = await finalization.calculate_closed_trade_stats(
        order_status,
        dependencies=_dependencies(trades=trades),
        partial_amount=0.5,
        partial_proceeds=60.0,
    )

    payload = result["payload"]
    assert trades.partial_reads == 0
    # 0.5 @ 60 + 1.0 @ 120 = 180 over 1.5 for a 200 cost basis.
    assert payload["amount"] == pytest.approx(1.5)
    assert payload["tp_price"] == pytest.approx(120.0)
    assert payload["avg_price"] == pytest.approx(200.0 / 1.5)
    assert payload["profit"] == pytest.approx(-20.0)
    assert payload["profit_percent"] == pytest.approx(-10.0)
    assert result["monitor_payload"]["amount"] == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_closed_trade_stats_zero_partials_close_on_final_fill_only() -> None:
    trades = _StatsTradeReader()
    order_status: dict[str, Any] = {
        "symbol": "BTC/USDC",
        "total_cost": 200.0,
        "total_amount": 1.0,
        "price": 120.0,
        "timestamp": 1700000100000,
        "close_reason": "manual_stop",
    }

    result = await finalization.calculate_closed_trade_stats(
        order_status,
        dependencies=_dependencies(trades=trades),
        partial_amount=0.0,
        partial_proceeds=0.0,
    )

    payload = result["payload"]
    assert trades.partial_reads == 0
    assert payload["amount"] == pytest.approx(1.0)
    assert payload["tp_price"] == pytest.approx(120.0)
    assert payload["avg_price"] == pytest.approx(200.0)
    assert payload["profit"] == pytest.approx(-80.0)
    assert payload["profit_percent"] == pytest.approx(-40.0)


def _buy_status(**overrides: Any) -> dict[str, Any]:
    """A filled exchange buy payload carrying every persistence key."""
    status: dict[str, Any] = {
        "timestamp": 1_700_000_000_000,
        "ordersize": 17.0,
        "fees": 0.01,
        "precision": 2,
        "amount_fee": 0.0,
        "amount": 1025.0,
        "price": 0.0166,
        "symbol": "TUT/USDC",
        "orderid": "test-order",
        "botname": "symsignal_tutusdc",
        "ordertype": "market",
        "baseorder": True,
        "safetyorder": False,
        "order_count": 0,
        "so_percentage": None,
        "direction": "long",
        "side": "buy",
    }
    status.update(overrides)
    return status


class _BuyFinalizationRecorder:
    """Captures persistence and monitoring calls made during finalization."""

    def __init__(self) -> None:
        self.persisted: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.notifications: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.persist_log_calls: list[str | None] = []

    async def persist_buy_trade(
        self,
        symbol: str,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        self.persisted.append((symbol, payload, kwargs))

    async def notify_trade(
        self,
        event: str,
        payload: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        self.notifications.append((event, payload, config))

    def log_persisted(self, operation_id: str | None, **kwargs: Any) -> None:
        self.persist_log_calls.append(operation_id)


async def _noop_reset(_symbol: str, *, dependencies: Any = None) -> None:
    return None


def _finalize_dependencies(recorder: _BuyFinalizationRecorder) -> Any:
    return finalization.DcaFinalizationContext(
        trades=_UnusedCollaborator(),
        monitoring=recorder,
        placement_workflow=recorder,
        exchange=_UnusedCollaborator(),
        utils=helper.Utils(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "order_status",
    [
        pytest.param(_buy_status(price=0.0), id="zero_price"),
        pytest.param(_buy_status(amount=0.0), id="zero_amount"),
        pytest.param(_buy_status(amount=-1.0), id="negative_amount"),
        pytest.param(
            {key: value for key, value in _buy_status().items() if key != "price"},
            id="missing_price",
        ),
    ],
)
async def test_finalize_buy_order_skips_persistence_for_invalid_fill(
    monkeypatch: pytest.MonkeyPatch,
    order_status: dict[str, Any],
) -> None:
    """An exchange payload without a core filled value is never persisted.

    Value: protects=a failed or zero-quantity exchange result cannot create
        a trade row or a Telegram notification; finalize reports False so
        the caller keeps the placement unresolved.
    fails_when=the fill validation stops failing closed and an empty fill
        reaches persistence or monitoring.
    why_new=the only prior finalize_buy_order test monkeypatched the
        validation to True, so the fail-closed branch itself was untested.
    seam=none (persistence and unsellable reset are the module's own
        collaborators and are recorded, not production seams).
    """
    recorder = _BuyFinalizationRecorder()
    monkeypatch.setattr(finalization, "persist_buy_trade", recorder.persist_buy_trade)
    monkeypatch.setattr(finalization, "reset_unsellable_state", _noop_reset)

    result = await finalization.finalize_buy_order(
        dict(order_status),
        {},
        original_order=dict(order_status),
        dependencies=_finalize_dependencies(recorder),
    )

    assert result is False
    assert recorder.persisted == []
    assert recorder.notifications == []
    assert recorder.persist_log_calls == []


_POLICY_CONFIG = {"dynamic_dca": True, "dca_strategy": "ema20_swing"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "config", "expected_metadata"),
    [
        pytest.param(
            _buy_status(
                safetyorder=True,
                baseorder=False,
                order_count=1,
                price=105.0,
                amount=2.0,
                metadata_json=json.dumps(
                    {
                        "recovery_so": {
                            "reference_price": 100.0,
                            "current_price": 102.0,
                        }
                    }
                ),
            ),
            {},
            {
                "recovery_so": {
                    "reference_price": 100.0,
                    "current_price": 102.0,
                    "fill_price": 105.0,
                    "fill_deviation_percent": 5.0,
                    "fill_vs_trigger_percent": round((105.0 - 102.0) / 102.0 * 100, 8),
                }
            },
            id="recovery_fill_evidence_recorded",
        ),
        pytest.param(
            _buy_status(),
            _POLICY_CONFIG,
            {"dca_policy": build_recovery_sizing_policy(_POLICY_CONFIG).to_dict()},
            id="dynamic_dca_base_order_policy_stamped",
        ),
    ],
)
async def test_finalize_buy_order_records_recovery_evidence_in_persisted_metadata(
    monkeypatch: pytest.MonkeyPatch,
    status: dict[str, Any],
    config: dict[str, Any],
    expected_metadata: dict[str, Any],
) -> None:
    """Recovery fill evidence and the deal policy reach the persisted row.

    Value: protects=a recovered safety-order fill records its fill price and
        deviation from the reference and trigger prices, and a dynamic-DCA
        base order persists the deal's recovery sizing policy, so the closed
        replay can explain how the order was sized.
    fails_when=finalize stops enriching the metadata before persistence and
        the execution ledger loses the deviation or policy evidence.
    why_new=no prior test asserted the recovery_so deviation fields or the
        base-order dca_policy stamp on the payload finalize persists.
    seam=none.
    """
    recorder = _BuyFinalizationRecorder()
    monkeypatch.setattr(finalization, "persist_buy_trade", recorder.persist_buy_trade)
    monkeypatch.setattr(finalization, "reset_unsellable_state", _noop_reset)

    result = await finalization.finalize_buy_order(
        status,
        config,
        original_order=dict(status),
        dependencies=_finalize_dependencies(recorder),
    )

    assert result is True
    assert len(recorder.persisted) == 1
    symbol, payload, _kwargs = recorder.persisted[0]
    assert symbol == status["symbol"]
    persisted_metadata = json.loads(payload["metadata_json"])
    for key, expected_value in expected_metadata.items():
        assert persisted_metadata[key] == expected_value, key
    assert [event for event, _payload, _config in recorder.notifications] == [
        "trade.buy"
    ]
