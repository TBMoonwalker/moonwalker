"""Regression coverage for Waiting campaign replay indicators."""

from __future__ import annotations

import os
from typing import Any

import model
import pytest
from service import trade_replay_indicators as replay_module
from service.trade_replay_indicators import (
    ReplayIndicatorCandle,
    TradeReplayIndicatorService,
)
from service.trades import Trades
from tortoise import Tortoise

CURRENT_DEAL_ID = "11111111-1111-4111-8111-111111111111"
PREVIOUS_DEAL_ID = "22222222-2222-4222-8222-222222222222"
CAMPAIGN_ID = "33333333-3333-4333-8333-333333333333"


class _FakeBuilder:
    """Return a deterministic overlay for the persisted strategy."""

    def __init__(self, symbol: str, timeframe: str) -> None:
        self.symbol = symbol
        self.timeframe = timeframe

    async def collect_strategy_requirements(self, *slugs: str) -> list[str]:
        return list(slugs)

    def required_warmup_candles(self) -> int:
        return 0

    async def build(
        self,
        indicators: Any,
        candles: list[ReplayIndicatorCandle],
        replay_start_index: int,
    ) -> list[dict[str, Any]]:
        return [
            {
                "key": "ema",
                "label": "EMA 20",
                "pane": "price",
                "renderer": "line",
                "color": "#B7791F",
                "values": [
                    {
                        "time": candles[replay_start_index].timestamp,
                        "value": 100.0,
                    }
                ],
            }
        ]


@pytest.mark.asyncio
async def test_waiting_replay_uses_campaign_strategy_when_current_deal_is_empty(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Waiting charts inherit strategy snapshots from prior campaign executions."""
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "test.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()

    await model.SpotCampaigns.create(
        campaign_id=CAMPAIGN_ID,
        symbol="BTC/USDC",
        lifecycle_mode="sidestep_reentry",
        state="flat_waiting_reentry",
        started_at="2026-07-01T08:00:00+00:00",
        last_transition_at="2026-07-02T08:00:00+00:00",
        current_deal_id=None,
        sidestep_count=1,
        tp_percent=5.0,
        principal_quote=100.0,
        reserved_quote=105.0,
        cumulative_realized_quote=5.0,
        cumulative_realized_percent=5.0,
        metadata_json="{}",
    )
    await model.TradeExecutions.create(
        deal_id=PREVIOUS_DEAL_ID,
        campaign_id=CAMPAIGN_ID,
        symbol="BTC/USDC",
        side="sell",
        role="sidestep_exit",
        timestamp="1782900000000",
        price=105.0,
        amount=1.0,
        ordersize=105.0,
        strategy_name="ema20_swing",
        timeframe="1h",
    )

    service = TradeReplayIndicatorService(Trades())

    async def fake_load_candles(
        *args: Any,
        **kwargs: Any,
    ) -> list[ReplayIndicatorCandle]:
        return [
            ReplayIndicatorCandle(
                timestamp=1_782_900_000_000,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=10.0,
            )
        ]

    monkeypatch.setattr(service, "_load_candles", fake_load_candles)
    monkeypatch.setattr(
        replay_module,
        "StrategyChartIndicatorBuilder",
        _FakeBuilder,
    )

    payload = await service.get_indicators(
        CURRENT_DEAL_ID,
        "1h",
        1_782_900_000_000,
        1_782_903_600_000,
        campaign_id=CAMPAIGN_ID,
    )

    assert payload["source"] == "execution_ledger"
    assert payload["strategies"] == ["ema20_swing"]
    assert payload["indicators"][0]["label"] == "EMA 20"

    await Tortoise.close_connections()
