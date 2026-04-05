"""Tests for exchange limit sell manager."""

import pytest
from service.exchange_contexts import LimitSellFillContext
from service.exchange_limit_sell_manager import ExchangeLimitSellManager


class _DummyLogger:
    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass

    def error(self, *_args, **_kwargs) -> None:
        pass


class _DummyExchange:
    def __init__(self, statuses: list[dict[str, object]] | None = None) -> None:
        self._statuses = list(statuses or [])
        self.cancel_calls = 0

    async def fetch_order(self, _order_id: str, _symbol: str) -> dict[str, object]:
        if self._statuses:
            return self._statuses.pop(0)
        return {"status": "open", "filled": 0.0, "amount": 1.0}

    async def cancel_order(self, _order_id: str, _symbol: str) -> None:
        self.cancel_calls += 1


@pytest.mark.asyncio
async def test_wait_for_limit_sell_fill_returns_closed_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = _DummyExchange(
        statuses=[
            {"status": "closed", "filled": 1.0, "amount": 1.0},
        ]
    )
    manager = ExchangeLimitSellManager(_DummyLogger(), get_exchange=lambda: exchange)

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("service.exchange_limit_sell_manager.asyncio.sleep", fake_sleep)

    status = await manager.wait_for_limit_sell_fill("BTC/USDT", "123", 1)

    assert status == {"status": "closed", "filled": 1.0, "amount": 1.0}


@pytest.mark.asyncio
async def test_cancel_order_and_confirm_returns_true_when_canceled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = _DummyExchange(
        statuses=[
            {"status": "canceled"},
        ]
    )
    manager = ExchangeLimitSellManager(_DummyLogger(), get_exchange=lambda: exchange)

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("service.exchange_limit_sell_manager.asyncio.sleep", fake_sleep)

    confirmed = await manager.cancel_order_and_confirm("BTC/USDT", "123")

    assert confirmed is True
    assert exchange.cancel_calls == 1


@pytest.mark.asyncio
async def test_handle_limit_sell_fill_returns_partial_fallback_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = _DummyExchange(
        statuses=[
            {
                "status": "open",
                "filled": 1.5,
                "remaining": 0.5,
                "average": 102.0,
                "price": 102.0,
            }
        ]
    )
    manager = ExchangeLimitSellManager(_DummyLogger(), get_exchange=lambda: exchange)

    async def fake_wait_for_limit_sell_fill(
        _symbol: str,
        _order_id: str,
        _timeout_seconds: int,
    ) -> dict[str, object] | None:
        return None

    async def fake_cancel_order_and_confirm(_symbol: str, _order_id: str) -> bool:
        return True

    async def fake_parse_order_status(
        _order: dict[str, object],
    ) -> dict[str, object]:
        return {"total_amount": 1.25, "price": 101.0}

    async def fake_build_sell_order_status(
        _order: dict[str, object],
    ) -> dict[str, object] | None:
        raise AssertionError("filled-order path should not be used")

    monkeypatch.setattr(
        manager,
        "wait_for_limit_sell_fill",
        fake_wait_for_limit_sell_fill,
    )
    monkeypatch.setattr(
        manager,
        "cancel_order_and_confirm",
        fake_cancel_order_and_confirm,
    )

    status = await manager.handle_limit_sell_fill(
        sell_order={"id": "123"},
        resolved_symbol="BTC/USDT",
        config={"limit_sell_timeout_sec": 10},
        original_order={},
        context=LimitSellFillContext(
            parse_order_status=fake_parse_order_status,
            build_sell_order_status=fake_build_sell_order_status,
        ),
    )

    assert status == {
        "requires_market_fallback": True,
        "limit_cancel_confirmed": True,
        "fallback_reason": "limit_order_partial_timeout",
        "symbol": "BTC/USDT",
        "remaining_amount": 0.5,
        "partial_filled_amount": 1.25,
        "partial_avg_price": 101.0,
        "executions": [
            {
                "symbol": "BTC/USDT",
                "side": "sell",
                "role": "partial_sell",
                "timestamp": "",
                "price": 101.0,
                "amount": 1.25,
                "ordersize": 126.25,
                "fee": 0.0,
                "order_id": "123",
                "order_type": "limit",
            }
        ],
    }


@pytest.mark.asyncio
async def test_handle_limit_sell_fill_marks_unconfirmed_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = _DummyExchange(
        statuses=[
            {"status": "open", "filled": 0.0, "remaining": 1.0},
        ]
    )
    manager = ExchangeLimitSellManager(_DummyLogger(), get_exchange=lambda: exchange)
    original_order: dict[str, object] = {}

    async def fake_wait_for_limit_sell_fill(
        _symbol: str,
        _order_id: str,
        _timeout_seconds: int,
    ) -> dict[str, object] | None:
        return None

    async def fake_cancel_order_and_confirm(_symbol: str, _order_id: str) -> bool:
        return False

    async def fake_parse_order_status(
        _order: dict[str, object],
    ) -> dict[str, object]:
        return {}

    async def fake_build_sell_order_status(
        _order: dict[str, object],
    ) -> dict[str, object] | None:
        return {}

    monkeypatch.setattr(
        manager,
        "wait_for_limit_sell_fill",
        fake_wait_for_limit_sell_fill,
    )
    monkeypatch.setattr(
        manager,
        "cancel_order_and_confirm",
        fake_cancel_order_and_confirm,
    )

    status = await manager.handle_limit_sell_fill(
        sell_order={"id": "123"},
        resolved_symbol="BTC/USDT",
        config={"limit_sell_timeout_sec": 10},
        original_order=original_order,
        context=LimitSellFillContext(
            parse_order_status=fake_parse_order_status,
            build_sell_order_status=fake_build_sell_order_status,
        ),
    )

    assert status == {
        "requires_market_fallback": True,
        "limit_cancel_confirmed": False,
        "fallback_reason": "limit_order_timeout",
        "symbol": "BTC/USDT",
        "remaining_amount": 0.0,
        "partial_filled_amount": 0.0,
        "partial_avg_price": 0.0,
    }
    assert original_order["_limit_cancel_confirmed"] is False
