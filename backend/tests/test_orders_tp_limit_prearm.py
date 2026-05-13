"""Tests for proactive TP limit order lifecycle handling."""

from typing import Any

import pytest
from service.orders import Orders


class _FakeExchange:
    def __init__(self) -> None:
        self.placed_orders: list[dict[str, Any]] = []
        self.cancel_calls: list[tuple[str, str]] = []
        self.closed = False
        self.fetch_status: dict[str, Any] = {
            "status": "open",
            "filled": 0.0,
            "amount": 1.0,
        }
        self.cancel_status: dict[str, Any] = {
            "status": "canceled",
            "filled": 0.0,
            "amount": 1.0,
        }

    async def place_spot_limit_sell(
        self,
        order: dict[str, Any],
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        self.placed_orders.append(order)
        return {
            "id": "tp-limit-1",
            "symbol": order["symbol"],
            "price": order["limit_price"],
            "total_amount": order["total_amount"],
        }

    async def fetch_spot_order(
        self,
        _symbol: str,
        _order_id: str,
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        return dict(self.fetch_status)

    async def cancel_spot_order(
        self,
        symbol: str,
        order_id: str,
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        self.cancel_calls.append((symbol, order_id))
        return dict(self.cancel_status)

    async def close(self) -> None:
        self.closed = True


class _FakeTrades:
    def __init__(self) -> None:
        self.persisted_order: dict[str, Any] | None = None
        self.cleared_symbols: list[str] = []
        self.partial_fills: list[dict[str, Any]] = []
        self.invalidated = 0

    async def set_tp_limit_order(
        self,
        symbol: str,
        *,
        order_id: str,
        price: float,
        amount: float,
    ) -> bool:
        self.persisted_order = {
            "symbol": symbol,
            "order_id": order_id,
            "price": price,
            "amount": amount,
        }
        return True

    async def get_open_trades_by_symbol(self, symbol: str) -> list[dict[str, Any]]:
        return [{"symbol": symbol, "tp_limit_order_id": "tp-limit-1"}]

    async def get_trades_for_orders(self, symbol: str) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "tp_limit_order_id": "tp-limit-1",
            "total_cost": 100.0,
            "total_amount": 1.0,
            "tp_limit_order_price": 110.0,
            "tp_limit_order_amount": 1.0,
            "current_price": 109.0,
        }

    async def clear_tp_limit_order(self, symbol: str) -> bool:
        self.cleared_symbols.append(symbol)
        return True

    async def add_partial_sell_execution(
        self,
        symbol: str,
        sold_amount: float,
        sold_proceeds: float,
        sell_executions: list[dict[str, Any]],
    ) -> None:
        self.partial_fills.append(
            {
                "symbol": symbol,
                "sold_amount": sold_amount,
                "sold_proceeds": sold_proceeds,
                "sell_executions": sell_executions,
            }
        )

    async def invalidate_trade_caches(self) -> None:
        self.invalidated += 1


@pytest.mark.asyncio
async def test_arm_tp_limit_order_places_and_persists_order() -> None:
    orders = Orders()
    fake_exchange = _FakeExchange()
    fake_trades = _FakeTrades()
    orders.exchange = fake_exchange  # type: ignore[assignment]
    orders.trades = fake_trades  # type: ignore[assignment]

    armed = await orders.arm_tp_limit_order(
        {
            "symbol": "XPL/USDC",
            "total_amount": 1.0,
            "limit_price": 110.0,
        },
        {},
    )

    assert armed is True
    assert fake_exchange.placed_orders[0]["limit_price"] == 110.0
    assert fake_trades.persisted_order == {
        "symbol": "XPL/USDC",
        "order_id": "tp-limit-1",
        "price": 110.0,
        "amount": 1.0,
    }
    assert fake_exchange.closed is True


@pytest.mark.asyncio
async def test_cancel_tp_limit_order_clears_persisted_metadata() -> None:
    orders = Orders()
    fake_exchange = _FakeExchange()
    fake_trades = _FakeTrades()
    orders.exchange = fake_exchange  # type: ignore[assignment]
    orders.trades = fake_trades  # type: ignore[assignment]

    canceled = await orders.cancel_tp_limit_order("XPL/USDC", {})

    assert canceled is True
    assert fake_exchange.cancel_calls == [("XPL/USDC", "tp-limit-1")]
    assert fake_trades.cleared_symbols == ["XPL/USDC"]


@pytest.mark.asyncio
async def test_cancel_tp_limit_order_persists_partial_fill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orders = Orders()
    fake_exchange = _FakeExchange()
    fake_exchange.cancel_status = {
        "id": "tp-limit-1",
        "symbol": "XPL/USDC",
        "status": "canceled",
        "filled": 0.4,
        "amount": 1.0,
        "average": 111.0,
        "cost": 44.4,
        "timestamp": 1_742_000_000_123,
    }
    fake_trades = _FakeTrades()
    orders.exchange = fake_exchange  # type: ignore[assignment]
    orders.trades = fake_trades  # type: ignore[assignment]
    persisted_partials: list[dict[str, Any]] = []

    async def fake_persist_partial_sell_execution(
        symbol: str,
        sold_amount: float,
        sold_proceeds: float,
        sell_executions: list[dict[str, Any]],
    ) -> None:
        persisted_partials.append(
            {
                "symbol": symbol,
                "sold_amount": sold_amount,
                "sold_proceeds": sold_proceeds,
                "sell_executions": sell_executions,
            }
        )

    monkeypatch.setattr(
        "service.orders.persist_partial_sell_execution",
        fake_persist_partial_sell_execution,
    )

    canceled = await orders.cancel_tp_limit_order("XPL/USDC", {})

    assert canceled is True
    assert persisted_partials == [
        {
            "symbol": "XPL/USDC",
            "sold_amount": 0.4,
            "sold_proceeds": 44.4,
            "sell_executions": [
                {
                    "symbol": "XPL/USDC",
                    "side": "sell",
                    "role": "partial_sell",
                    "timestamp": "1742000000123",
                    "price": 111.0,
                    "amount": 0.4,
                    "ordersize": 44.4,
                    "fee": 0.0,
                    "order_id": "tp-limit-1",
                    "order_type": "limit",
                }
            ],
        }
    ]
    assert fake_trades.cleared_symbols == ["XPL/USDC"]


@pytest.mark.asyncio
async def test_reconcile_tp_limit_order_handles_unsellable_partial_fill(
    monkeypatch,
) -> None:
    orders = Orders()
    fake_exchange = _FakeExchange()
    fake_exchange.fetch_status = {
        "id": "tp-limit-1",
        "symbol": "TWT/USDC",
        "status": "filled",
        "filled": 25.0,
        "amount": 25.0,
    }
    fake_trades = _FakeTrades()

    async def fake_get_trades_for_orders(symbol: str) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "tp_limit_order_id": "tp-limit-1",
            "total_cost": 11.3412,
            "fee": 0.001,
            "total_amount": 25.9753,
            "sellable_amount": 25.9753,
            "tp_limit_order_price": 0.4414,
            "tp_limit_order_amount": 25.0,
            "current_price": 0.4414,
        }

    fake_trades.get_trades_for_orders = fake_get_trades_for_orders  # type: ignore[assignment]
    orders.exchange = fake_exchange  # type: ignore[assignment]
    orders.trades = fake_trades  # type: ignore[assignment]

    async def fake_build_spot_sell_order_status(
        _payload: dict[str, Any],
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "type": "partial_sell",
            "symbol": "TWT/USDC",
            "partial_filled_amount": 25.0,
            "partial_avg_price": 0.4414,
            "partial_proceeds": 11.035,
            "remaining_amount": 0.9753,
            "unsellable": True,
            "unsellable_reason": "amount_precision",
        }

    handled: list[dict[str, Any]] = []

    async def fake_handle_partial(
        order_status: dict[str, Any],
        _config: dict[str, Any],
    ) -> None:
        handled.append(order_status)

    fake_exchange.build_spot_sell_order_status = fake_build_spot_sell_order_status  # type: ignore[attr-defined]
    monkeypatch.setattr(
        orders, "_Orders__handle_partial_sell_status", fake_handle_partial
    )

    reconciled = await orders.reconcile_tp_limit_order(
        {
            "symbol": "TWT/USDC",
            "tp_limit_order_id": "tp-limit-1",
            "total_cost": 11.3412,
            "fee": 0.001,
            "total_amount": 25.9753,
            "sellable_amount": 25.9753,
            "tp_limit_order_price": 0.4414,
            "tp_limit_order_amount": 25.0,
            "current_price": 0.4414,
        },
        {},
    )

    assert reconciled is True
    assert handled == [
        {
            "type": "partial_sell",
            "symbol": "TWT/USDC",
            "partial_filled_amount": 25.0,
            "partial_avg_price": 0.4414,
            "partial_proceeds": 11.035,
            "remaining_amount": 0.9753,
            "unsellable": True,
            "unsellable_reason": "amount_precision",
        }
    ]
    assert fake_trades.cleared_symbols == ["TWT/USDC"]
