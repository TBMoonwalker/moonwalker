"""Regression tests for locked lifecycle snapshot revalidation."""

from __future__ import annotations

from typing import Any

import pytest
from service.lifecycle_snapshot import (
    LifecycleSnapshotIdentity,
    build_config_revision,
    snapshots_match,
)
from service.orders import Orders


def _trade(**overrides: Any) -> dict[str, Any]:
    trade = {
        "symbol": "BTC/USDC",
        "deal_id": "deal-1",
        "campaign_id": "campaign-1",
        "execution_count": 2,
        "safetyorders_count": 1,
        "automation_paused": False,
        "exposure_state": "long_exposed",
        "tp_limit_order_id": None,
        "dca_sizing_mode": "legacy_factors",
        "dca_policy_json": None,
        "dca_reference_price": 100.0,
        "dca_reference_atr_percent": 2.0,
        "dca_next_trigger_price": 95.0,
    }
    trade.update(overrides)
    return trade


def test_snapshot_revision_is_deterministic_and_secret_opaque() -> None:
    config = {"dry_run": True, "api_secret": "do-not-expose", "bo": 25.0}

    first = build_config_revision(config)
    second = build_config_revision(
        {"bo": 25.0, "api_secret": "do-not-expose", "dry_run": True}
    )

    assert first == second
    assert "do-not-expose" not in first
    assert len(first) == 64


def test_snapshot_falls_back_to_safety_order_count_and_normalizes_optional_ids() -> (
    None
):
    snapshot = LifecycleSnapshotIdentity.from_trade(
        _trade(
            execution_count=None,
            safetyorders_count=2,
            deal_id=" ",
            campaign_id=None,
        ),
        {"dry_run": True},
    )

    assert snapshot.execution_count == 3
    assert snapshot.deal_id is None
    assert snapshot.campaign_id is None


def test_snapshot_never_matches_a_missing_locked_trade() -> None:
    snapshot = LifecycleSnapshotIdentity.from_trade(
        _trade(),
        {"dry_run": True},
    )

    assert snapshots_match(snapshot, None, {"dry_run": True}) is False


@pytest.mark.parametrize(
    ("changed_state", "changed_config"),
    [
        ({"deal_id": "deal-2"}, None),
        ({"campaign_id": "campaign-2"}, None),
        ({"execution_count": 3}, None),
        ({"automation_paused": True}, None),
        ({"exposure_state": "flat_waiting_reentry"}, None),
        ({"tp_limit_order_id": "limit-1"}, None),
        ({"dca_next_trigger_price": 90.0}, None),
        ({}, {"dry_run": True, "bo": 50.0}),
    ],
)
def test_snapshot_detects_every_execution_identity_change(
    changed_state: dict[str, Any],
    changed_config: dict[str, Any] | None,
) -> None:
    config = {"dry_run": True, "bo": 25.0}
    expected = LifecycleSnapshotIdentity.from_trade(_trade(), config)

    assert not snapshots_match(
        expected,
        _trade(**changed_state),
        changed_config or config,
    )


class _FreshTradeReader:
    def __init__(self, current_trade: dict[str, Any]) -> None:
        self.current_trade = current_trade
        self.fresh_reads = 0

    async def get_trades_for_orders_fresh(
        self,
        _symbol: str,
    ) -> dict[str, Any]:
        self.fresh_reads += 1
        return self.current_trade


@pytest.mark.asyncio
async def test_stale_buy_decision_aborts_before_any_exchange_work() -> None:
    config = {"dry_run": True, "bo": 25.0}
    evaluated_trade = _trade()
    reader = _FreshTradeReader(_trade(execution_count=3))
    orders = Orders()
    orders.trades = reader  # type: ignore[assignment]
    order = {
        "symbol": "BTC/USDC",
        "lifecycle_snapshot": LifecycleSnapshotIdentity.from_trade(
            evaluated_trade,
            config,
        ).to_dict(),
    }

    result = await orders.receive_buy_order(order, config)

    assert result is False
    assert reader.fresh_reads == 1


@pytest.mark.asyncio
async def test_invalid_snapshot_fails_closed_before_trade_loading() -> None:
    orders = Orders()
    order = {
        "symbol": "BTC/USDC",
        "lifecycle_snapshot": {"execution_count": "not-an-integer"},
    }

    result = await orders.receive_buy_order(order, {"dry_run": True})

    assert result is False


@pytest.mark.asyncio
async def test_matching_and_absent_snapshots_remain_admissible() -> None:
    config = {"dry_run": True, "bo": 25.0}
    current_trade = _trade()
    reader = _FreshTradeReader(current_trade)
    orders = Orders()
    orders.trades = reader  # type: ignore[assignment]

    assert await orders._order_snapshot_is_current(
        {"symbol": "BTC/USDC"},
        config,
    )
    assert await orders._order_snapshot_is_current(
        {
            "symbol": "BTC/USDC",
            "lifecycle_snapshot": LifecycleSnapshotIdentity.from_trade(
                current_trade,
                config,
            ).to_dict(),
        },
        config,
    )
    assert reader.fresh_reads == 1
