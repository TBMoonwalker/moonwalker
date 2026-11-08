"""Regression coverage for stamping the active DCA strategy onto base orders.

Value: protects=a dynamic DCA deal whose base order carries no entry-filter
    strategy still records the deal's DCA strategy, so its closed replay keeps
    the indicator overlays shown while the deal was open.
fails_when=the stamp stops applying to strategy-less base orders, overwrites an
    existing entry-filter strategy, or leaks into non-dynamic-DCA modes.
why_new=no prior test exercised base-order DCA strategy recording; the open-deal
    replay fallback masked the gap while deals were open.
"""

from __future__ import annotations

from typing import Any

import pytest
import service.orders as orders_module
from service.order_payloads import build_buy_trade_payload
from service.orders import Orders


def _buy_order_status(**overrides: Any) -> dict[str, Any]:
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


def _config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "dca_strategy": "ema20_swing",
        "trade_mode": "dynamic_dca",
    }
    config.update(overrides)
    return config


@pytest.mark.parametrize(
    ("status", "config", "expected_slug"),
    [
        pytest.param(
            _buy_order_status(),
            _config(),
            "ema20_swing",
            id="strategy_less_base_order_is_stamped",
        ),
        pytest.param(
            _buy_order_status(signal_name="sym_signals:62"),
            _config(),
            "ema20_swing",
            id="signal_name_alone_does_not_block_the_stamp",
        ),
        pytest.param(
            _buy_order_status(
                strategy_name="entry_filter",
                strategy_slug="entry_filter",
            ),
            _config(),
            "entry_filter",
            id="existing_entry_strategy_is_preserved",
        ),
        pytest.param(
            _buy_order_status(),
            _config(trade_mode="accumulation"),
            None,
            id="non_dynamic_dca_mode_is_not_stamped",
        ),
        pytest.param(
            _buy_order_status(),
            _config(dca_strategy=""),
            None,
            id="empty_dca_strategy_is_not_stamped",
        ),
        pytest.param(
            _buy_order_status(),
            _config(dca_strategy=None),
            None,
            id="missing_dca_strategy_is_not_stamped",
        ),
    ],
)
def test_stamp_deal_dca_strategy_branches(
    status: dict[str, Any],
    config: dict[str, Any],
    expected_slug: str | None,
) -> None:
    Orders._stamp_deal_dca_strategy(status, config)
    assert status.get("strategy_slug") == expected_slug
    assert status.get("strategy_name") == expected_slug


def test_stamped_strategy_reaches_the_persistence_payload() -> None:
    status = _buy_order_status()
    Orders._stamp_deal_dca_strategy(status, _config())
    payload = build_buy_trade_payload(status)
    assert payload["strategy_slug"] == "ema20_swing"
    assert payload["strategy_name"] == "ema20_swing"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_slug"),
    [
        pytest.param(
            _buy_order_status(),
            "ema20_swing",
            id="base_order_is_stamped_by_finalize",
        ),
        pytest.param(
            _buy_order_status(
                baseorder=False,
                safetyorder=True,
                order_count=1,
            ),
            None,
            id="safety_order_is_left_to_the_engine_stamp",
        ),
    ],
)
async def test_finalize_buy_order_applies_the_stamp_to_base_orders_only(
    monkeypatch: pytest.MonkeyPatch,
    status: dict[str, Any],
    expected_slug: str | None,
) -> None:
    orders = Orders()
    captured: dict[str, Any] = {}

    async def fake_persist_buy_trade(symbol: str, payload: Any, **kwargs: Any) -> None:
        captured["symbol"] = symbol
        captured["payload"] = payload
        captured["kwargs"] = kwargs

    async def fake_notify_trade(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def fake_reset_unsellable(_symbol: str) -> None:
        return None

    def fake_log_persisted(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(orders_module, "persist_buy_trade", fake_persist_buy_trade)
    monkeypatch.setattr(
        Orders, "_has_valid_buy_fill", staticmethod(lambda _status: True)
    )
    monkeypatch.setattr(orders.placement_workflow, "log_persisted", fake_log_persisted)
    monkeypatch.setattr(orders, "_reset_unsellable_state", fake_reset_unsellable)
    monkeypatch.setattr(orders.monitoring, "notify_trade", fake_notify_trade)

    finalized = await orders._finalize_buy_order(
        status,
        _config(),
        original_order=dict(status),
    )

    assert finalized is True
    payload = captured["payload"]
    assert payload["strategy_slug"] == expected_slug
    assert payload["strategy_name"] == expected_slug
