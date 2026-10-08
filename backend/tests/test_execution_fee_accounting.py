"""Regression coverage for CCXT fee normalization and execution metadata."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from service.feedback_accounting import execution_accounting, merge_accounting_metadata


@pytest.mark.parametrize(
    "fee",
    [
        None,
        {"cost": None},
        {"cost": "bad"},
        {"cost": float("inf")},
        {"cost": -1},
        {"cost": 1, "currency": "BNB"},
    ],
)
def test_invalid_fee_information_blocks_accounting(fee):
    result = execution_accounting(
        [{"side": "sell", "price": 100, "fee": fee}], "BTC/USDC"
    )
    assert result["complete"] is False


def test_zero_fee_and_multiple_fee_currencies_preserve_cash_flow():
    result = execution_accounting(
        [
            {
                "side": "buy",
                "price": 100,
                "fees": [
                    {"cost": 0.001, "currency": "BTC"},
                    {"cost": 0.2, "currency": "USDC"},
                ],
            },
            {"side": "sell", "price": 110, "fee": {"cost": 0, "currency": None}},
        ],
        "BTC/USDC",
    )
    assert result == {
        "complete": True,
        "fees_quote": pytest.approx(0.3),
        "external_buy_fees": 0.2,
        "sell_fees": 0.0,
    }


@pytest.mark.parametrize("use_lookup", [True, False])
def test_normalized_sell_accounting_survives_final_execution_payload(use_lookup):
    from datetime import UTC, datetime

    from service.exchange_helpers import aggregate_matched_trades
    from service.exchange_order_lookup import build_parsed_order_status
    from service.exchange_sell_status import finalize_sell_order_status
    from service.order_payloads import build_final_sell_executions

    fill = {
        "id": "sell-1",
        "order": "sell-1",
        "symbol": "BTC/USDC",
        "side": "sell",
        "timestamp": 1000,
        "amount": 1.0,
        "price": 110.0,
        "cost": 110.0,
        "fee": {"cost": 0.11, "currency": "USDC"},
    }
    parsed = build_parsed_order_status(
        fill, aggregate_matched_trades([fill], "BTC/USDC") if use_lookup else None
    )
    # Normal finalization and the fallback payload path both retain exact metadata.
    normalized = finalize_sell_order_status(parsed, total_cost=100, actual_pnl=10)
    execution_rows = build_final_sell_executions(
        normalized, closed_at=datetime.now(UTC)
    )
    fallback_rows = (
        build_final_sell_executions(
            {**normalized, "executions": []}, closed_at=datetime.now(UTC)
        )
        if use_lookup
        else []
    )
    for row in execution_rows + fallback_rows:
        assert json.loads(row["metadata_json"])["feedback_accounting"][
            "sell_fees"
        ] == pytest.approx(0.11)


@pytest.mark.asyncio
async def test_buy_finalization_preserves_signal_and_accounts_base_fee_once():
    from unittest.mock import MagicMock

    from service.exchange_buy_manager import ExchangeBuyManager
    from service.exchange_contexts import BuyFinalizationContext

    exchange = SimpleNamespace(
        fetch_trading_fee=AsyncMock(return_value={"taker": 0.001})
    )
    manager = ExchangeBuyManager(MagicMock(), get_exchange=lambda: exchange)
    for dry_run in (True, False):
        for fee_deduction in (True, False):
            accounting = execution_accounting(
                [
                    {
                        "side": "buy",
                        "price": 100,
                        "fee": {"cost": 0.001, "currency": "BTC"},
                    }
                ],
                "BTC/USDC",
            )
            parsed = {
                "symbol": "BTC/USDC",
                "amount": 1,
                "base_fee": 0.001,
                "price": 100,
                "metadata_json": merge_accounting_metadata(None, accounting),
            }
            result = await manager.finalize_market_buy(
                order={
                    "symbol": "BTC/USDC",
                    "metadata_json": json.dumps(
                        {
                            "websocket_signal": {"signal_id": "sig-1"},
                            "dca_policy": {"mode": "legacy_factors"},
                        }
                    ),
                },
                config={"dry_run": dry_run, "fee_deduction": fee_deduction},
                context=BuyFinalizationContext(
                    parse_order_status=AsyncMock(return_value=parsed),
                    get_precision_for_symbol=AsyncMock(return_value=6),
                    resolve_symbol=AsyncMock(return_value="BTC/USDC"),
                    get_demo_taker_fee_for_symbol=lambda _: 0.001,
                ),
            )
            metadata = json.loads(result["metadata_json"])
            assert metadata["websocket_signal"] == {"signal_id": "sig-1"}
            assert metadata["dca_policy"] == {"mode": "legacy_factors"}
            assert metadata["feedback_accounting"]["fees_quote"] == pytest.approx(0.1)
            assert metadata["feedback_accounting"][
                "external_buy_fees"
            ] == pytest.approx(0.1 if fee_deduction else 0)
            assert result["amount"] == pytest.approx(1 if fee_deduction else 0.999)


@pytest.mark.asyncio
@pytest.mark.parametrize("lookup_available", [True, False])
@pytest.mark.parametrize("multiple_fees", [True, False])
async def test_ccxt_base_fees_reach_inventory_and_metadata(
    lookup_available, multiple_fees
):
    """Fees-only fills and order fallbacks must reduce purchased inventory."""
    from unittest.mock import MagicMock

    from service.exchange_buy_manager import ExchangeBuyManager
    from service.exchange_contexts import BuyFinalizationContext
    from service.exchange_helpers import aggregate_matched_trades
    from service.exchange_order_lookup import build_parsed_order_status

    fee = {"cost": 0.001, "currency": "BTC"}
    fill = {
        "id": "order-1",
        "order": "order-1",
        "symbol": "BTC/USDC",
        "side": "buy",
        "amount": 1,
        "price": 100,
        "cost": 100,
        "timestamp": 1,
        "fee": None if multiple_fees else fee,
    }
    if multiple_fees:
        fill["fees"] = [fee]
    trade = aggregate_matched_trades([fill], "BTC/USDC") if lookup_available else None
    parsed = build_parsed_order_status(fill, trade)
    assert parsed["base_fee"] == pytest.approx(0.001)
    assert parsed["amount_fee"] == pytest.approx(0.001)
    manager = ExchangeBuyManager(MagicMock(), get_exchange=lambda: SimpleNamespace())
    result = await manager.finalize_market_buy(
        order={
            "symbol": "BTC/USDC",
            "metadata_json": merge_accounting_metadata(
                None,
                execution_accounting(
                    [
                        {
                            "side": "buy",
                            "price": 100,
                            "fee": {"cost": 0, "currency": "USDC"},
                        }
                    ],
                    "BTC/USDC",
                ),
            ),
        },
        config={"dry_run": True, "fee_deduction": False},
        context=BuyFinalizationContext(
            parse_order_status=AsyncMock(return_value=parsed),
            get_precision_for_symbol=AsyncMock(return_value=6),
            resolve_symbol=AsyncMock(return_value="BTC/USDC"),
            get_demo_taker_fee_for_symbol=lambda _: 0.001,
        ),
    )
    assert result["amount"] == pytest.approx(0.999)
    accounting = json.loads(result["metadata_json"])["feedback_accounting"]
    assert accounting["fees_quote"] == pytest.approx(0.1)
    assert accounting["external_buy_fees"] == 0
