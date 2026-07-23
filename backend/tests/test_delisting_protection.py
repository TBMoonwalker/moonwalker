"""Regression coverage for optional exchange delisting protection."""

from __future__ import annotations

from typing import Any

import pytest
from service.delisting_protection import (
    DelistingDecision,
    DelistingProtectionService,
)
from service.orders import Orders


class FakeDelistingExchange:
    """Small exchange seam used to exercise provider and status behavior."""

    def __init__(
        self,
        *,
        markets: list[dict[str, Any]],
        schedule: list[dict[str, Any]] | None = None,
        schedule_error: Exception | None = None,
    ) -> None:
        self.markets = markets
        self.schedule = schedule or []
        self.schedule_error = schedule_error
        self.market_calls = 0
        self.schedule_calls = 0
        self.close_calls = 0

    async def fetch_market_metadata(
        self,
        _config: dict[str, Any],
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        assert force_refresh is True
        self.market_calls += 1
        return self.markets

    async def fetch_spot_delist_schedule(
        self,
        _config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        self.schedule_calls += 1
        if self.schedule_error is not None:
            raise self.schedule_error
        return self.schedule

    async def close(self) -> None:
        self.close_calls += 1


async def _disable_open_trade_notifications(
    service: DelistingProtectionService,
) -> None:
    """Keep unit refreshes independent from the database runtime."""

    async def get_open_trades() -> list[dict[str, Any]]:
        return []

    service.trades.get_open_trades = get_open_trades  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_binance_schedule_blocks_matching_ccxt_symbol() -> None:
    service = DelistingProtectionService()
    await _disable_open_trade_notifications(service)
    service.config = {
        "delisting_protection_enabled": True,
        "exchange": "binance",
        "market": "spot",
        "dry_run": False,
    }
    service.exchange = FakeDelistingExchange(  # type: ignore[assignment]
        markets=[
            {
                "id": "ADAUSDT",
                "symbol": "ADA/USDT",
                "active": True,
            }
        ],
        schedule=[
            {
                "delistTime": 1_900_000_000_000,
                "symbols": ["ADAUSDT"],
            }
        ],
    )

    await service.refresh(service.config)
    decision = await service.evaluate_buy("ADA/USDT", service.config)

    assert decision.allowed is False
    assert decision.reason_code == "blocked_scheduled_delisting"
    assert decision.source == "binance_spot_schedule"
    assert decision.delist_at is not None


@pytest.mark.asyncio
async def test_generic_ccxt_market_status_blocks_inactive_market() -> None:
    service = DelistingProtectionService()
    await _disable_open_trade_notifications(service)
    service.config = {
        "delisting_protection_enabled": True,
        "exchange": "kraken",
        "market": "spot",
        "dry_run": False,
    }
    service.exchange = FakeDelistingExchange(  # type: ignore[assignment]
        markets=[
            {
                "id": "CVCUSDC",
                "symbol": "CVC/USDC",
                "active": False,
            }
        ]
    )

    await service.refresh(service.config)
    decision = await service.evaluate_buy("CVC/USDC", service.config)

    assert decision.allowed is False
    assert decision.reason_code == "blocked_market_inactive"
    assert decision.source == "ccxt_market_status"


@pytest.mark.asyncio
async def test_generic_unknown_active_status_is_allowed_as_degraded() -> None:
    service = DelistingProtectionService()
    await _disable_open_trade_notifications(service)
    service.config = {
        "delisting_protection_enabled": True,
        "exchange": "kraken",
        "market": "spot",
        "dry_run": False,
    }
    service.exchange = FakeDelistingExchange(  # type: ignore[assignment]
        markets=[
            {
                "id": "BTCUSDT",
                "symbol": "BTC/USDT",
                "active": None,
            }
        ]
    )

    await service.refresh(service.config)
    decision = await service.evaluate_buy("BTC/USDT", service.config)

    assert decision.allowed is True
    assert decision.degraded is True


@pytest.mark.asyncio
async def test_live_binance_fails_closed_when_schedule_is_unavailable() -> None:
    service = DelistingProtectionService()
    await _disable_open_trade_notifications(service)
    service.config = {
        "delisting_protection_enabled": True,
        "exchange": "binance",
        "market": "spot",
        "dry_run": False,
    }
    service.exchange = FakeDelistingExchange(  # type: ignore[assignment]
        markets=[
            {
                "id": "BTCUSDT",
                "symbol": "BTC/USDT",
                "active": True,
            }
        ],
        schedule_error=RuntimeError("schedule unavailable"),
    )

    await service.refresh(service.config)
    decision = await service.evaluate_buy("BTC/USDT", service.config)

    assert decision.allowed is False
    assert decision.reason_code == "blocked_delisting_check_unavailable"


@pytest.mark.asyncio
async def test_disabled_protection_does_not_touch_exchange() -> None:
    service = DelistingProtectionService()
    fake_exchange = FakeDelistingExchange(markets=[])
    service.exchange = fake_exchange  # type: ignore[assignment]
    config = {
        "delisting_protection_enabled": False,
        "exchange": "binance",
        "market": "spot",
    }

    decision = await service.evaluate_buy("BTC/USDT", config)

    assert decision.allowed is True
    assert fake_exchange.market_calls == 0
    assert fake_exchange.schedule_calls == 0


@pytest.mark.asyncio
async def test_open_trade_warning_is_enriched_and_notified_once() -> None:
    service = DelistingProtectionService()
    service.config = {
        "delisting_protection_enabled": True,
        "exchange": "binance",
        "market": "spot",
        "dry_run": False,
        "monitoring_enabled": True,
    }
    service.exchange = FakeDelistingExchange(  # type: ignore[assignment]
        markets=[
            {
                "id": "ADAUSDT",
                "symbol": "ADA/USDT",
                "active": True,
            }
        ],
        schedule=[
            {
                "delistTime": 1_900_000_000_000,
                "symbols": ["ADAUSDT"],
            }
        ],
    )
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def get_open_trades() -> list[dict[str, Any]]:
        return [{"id": 1, "symbol": "ADA/USDT"}]

    async def notify(
        event_type: str,
        payload: dict[str, Any],
        _config: dict[str, Any],
    ) -> None:
        notifications.append((event_type, payload))

    service.trades.get_open_trades = get_open_trades  # type: ignore[method-assign]
    service.monitoring.notify_trade = notify  # type: ignore[method-assign]

    await service.refresh(service.config)
    await service.refresh(service.config)
    enriched = service.enrich_open_trades([{"id": 1, "symbol": "ADA/USDT"}])

    assert enriched[0]["delisting_warning"] is True
    assert enriched[0]["delisting_reason"] == "scheduled_delisting"
    assert len(notifications) == 1
    assert notifications[0][0] == "risk.delisting"
    assert notifications[0][1]["symbol"] == "ADA/USDT"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("baseorder", "safetyorder", "campaign_id"),
    (
        (True, False, None),
        (False, True, None),
        (True, False, "sidestep-campaign"),
    ),
)
async def test_central_order_guard_blocks_every_buy_role(
    monkeypatch: pytest.MonkeyPatch,
    baseorder: bool,
    safetyorder: bool,
    campaign_id: str | None,
) -> None:
    orders = Orders()
    executed = False

    async def get_existing_trade(_symbol: str) -> None:
        return None

    async def block_delisting_buy(
        _symbol: str,
        _config: dict[str, Any],
    ) -> DelistingDecision:
        return DelistingDecision(
            allowed=False,
            reason_code="blocked_scheduled_delisting",
            message="Scheduled for delisting.",
            source="binance_spot_schedule",
        )

    async def execute_buy(*_args: Any, **_kwargs: Any) -> None:
        nonlocal executed
        executed = True
        raise AssertionError("delisting guard must run before buy execution")

    monkeypatch.setattr(
        orders.trades,
        "get_trades_for_orders",
        get_existing_trade,
    )
    monkeypatch.setattr(
        orders.delisting_protection,
        "evaluate_buy",
        block_delisting_buy,
    )
    monkeypatch.setattr(orders, "_execute_budgeted_buy_order", execute_buy)

    accepted = await orders.receive_buy_order(
        {
            "symbol": "ADA/USDT",
            "ordersize": 25.0,
            "baseorder": baseorder,
            "safetyorder": safetyorder,
            "campaign_id": campaign_id,
        },
        {"delisting_protection_enabled": True},
    )

    assert accepted is False
    assert executed is False
