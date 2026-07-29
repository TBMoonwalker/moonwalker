#!/usr/bin/env python3
"""Exercise durable placement recovery from a disposable Moonwalker process."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from tortoise import Tortoise
from tortoise.transactions import in_transaction

import model
from service.exchange_capabilities import (
    ExchangeOrderLookupResult,
    ExchangeOrderLookupStatus,
)
from service.placement_intents import (
    NONTERMINAL_PLACEMENT_STATES,
    PlacementAction,
    PlacementIntentService,
    PlacementIntentState,
    deserialize_placement_payload,
    mark_placement_persisted_in_transaction,
)
from service.placement_reconciliation import PlacementReconciler

PROCESS_KILLED_EXIT_CODE = 86
LIVE_CONFIG = {
    "exchange": "binance",
    "market": "spot",
    "dry_run": False,
}
OPERATION_ID = "buy-process-crash"
DEAL_ID = "00000000-0000-0000-0000-000000000001"
SYMBOL = "BTC/USDC"
AMOUNT = 0.01
PRICE = 100.0
RESERVED_QUOTE = AMOUNT * PRICE


def _kill_process() -> None:
    """Simulate an uncatchable process stop without cleanup handlers."""
    os._exit(PROCESS_KILLED_EXIT_CODE)


class DurableFakeExchangeAdapter:
    """Invoke the fake exchange in a separate process for every request."""

    def __init__(self, script_path: Path, database_path: Path) -> None:
        self.script_path = script_path
        self.database_path = database_path

    async def _invoke(self, *arguments: str) -> Any:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(self.script_path),
            "--database",
            str(self.database_path),
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                "Durable fake exchange failed: "
                f"{stderr.decode('utf-8', errors='replace').strip()}"
            )
        return json.loads(stdout.decode("utf-8"))

    async def submit(self, client_order_id: str) -> dict[str, Any]:
        """Place one filled order through the external fake exchange."""
        result = await self._invoke(
            "submit",
            "--client-order-id",
            client_order_id,
            "--symbol",
            SYMBOL,
            "--side",
            "buy",
            "--amount",
            str(AMOUNT),
            "--price",
            str(PRICE),
        )
        if not isinstance(result, dict):
            raise RuntimeError("Fake exchange returned an invalid order")
        return result

    async def lookup_spot_order(
        self,
        _symbol: str,
        _config: dict[str, Any],
        *,
        exchange_order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> ExchangeOrderLookupResult:
        """Resolve an exchange order using the production typed lookup contract."""
        del exchange_order_id
        if not client_order_id:
            return ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.NOT_FOUND
            )
        result = await self._invoke(
            "lookup",
            "--client-order-id",
            client_order_id,
        )
        if result is None:
            return ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.NOT_FOUND
            )
        if not isinstance(result, dict):
            return ExchangeOrderLookupResult(
                status=ExchangeOrderLookupStatus.UNAVAILABLE,
                error_message="Fake exchange returned malformed lookup data.",
            )
        return ExchangeOrderLookupResult(
            status=ExchangeOrderLookupStatus.FOUND,
            order=result,
        )


async def _initialize_database(database_path: Path) -> None:
    await Tortoise.init(
        db_url=f"sqlite://{database_path}",
        modules={"models": ["model"]},
    )
    await Tortoise.generate_schemas()


async def _persist_execution(
    intent: Any,
    exchange_order: dict[str, Any],
) -> None:
    """Persist one recovered execution and its intent state atomically."""
    evidence = exchange_order or deserialize_placement_payload(intent.result_json)
    order_id = str(evidence.get("id") or intent.exchange_order_id or "")
    async with in_transaction() as connection:
        existing = await model.TradeExecutions.filter(
            deal_id=DEAL_ID,
            order_id=order_id,
        ).using_db(connection)
        if not existing:
            await model.TradeExecutions.create(
                deal_id=DEAL_ID,
                symbol=SYMBOL,
                side="buy",
                role="safety_order",
                timestamp=str(evidence.get("timestamp") or 1_780_000_000_000),
                price=float(evidence.get("average") or evidence.get("price") or PRICE),
                amount=float(evidence.get("filled") or evidence.get("amount") or AMOUNT),
                ordersize=float(evidence.get("cost") or RESERVED_QUOTE),
                order_id=order_id,
                order_type="market",
                using_db=connection,
            )
        await mark_placement_persisted_in_transaction(
            str(intent.operation_id),
            connection,
        )


async def _resume(
    intent: Any,
    exchange_order: dict[str, Any],
    _config: dict[str, Any],
) -> bool:
    await _persist_execution(intent, exchange_order)
    return True


async def _prepare_intent(service: PlacementIntentService) -> Any:
    preparation = await service.prepare(
        {
            "operation_id": OPERATION_ID,
            "symbol": SYMBOL,
            "deal_id": DEAL_ID,
            "ordersize": RESERVED_QUOTE,
            "maximum_buy_price": PRICE,
        },
        LIVE_CONFIG,
        action=PlacementAction.BUY,
        side="buy",
        order_type="market",
        requested_quote=RESERVED_QUOTE,
        requested_amount=AMOUNT,
        reserved_quote=RESERVED_QUOTE,
    )
    if preparation.intent is None or preparation.client_order_id is None:
        raise RuntimeError("Live placement did not create a durable intent")
    return preparation


async def _start(
    service: PlacementIntentService,
    exchange: DurableFakeExchangeAdapter,
    crash_point: str,
) -> None:
    if crash_point == "before_intent_commit":
        _kill_process()

    preparation = await _prepare_intent(service)
    if crash_point == "after_intent_commit_before_submission":
        _kill_process()

    claimed = await service.claim_submission(preparation.operation_id)
    if not claimed:
        raise RuntimeError("The first process did not claim exchange submission")
    exchange_order = await exchange.submit(preparation.client_order_id)
    if crash_point == "after_exchange_acceptance_before_response":
        _kill_process()

    await service.transition(
        preparation.operation_id,
        PlacementIntentState.FILLED,
        exchange_order_id=str(exchange_order["id"]),
        result=exchange_order,
    )
    if crash_point == "after_response_before_trade_persistence":
        _kill_process()

    if crash_point == "during_sqlite_transaction":
        async with in_transaction() as connection:
            await model.TradeExecutions.create(
                deal_id=DEAL_ID,
                symbol=SYMBOL,
                side="buy",
                role="safety_order",
                timestamp=str(exchange_order["timestamp"]),
                price=float(exchange_order["average"]),
                amount=float(exchange_order["filled"]),
                ordersize=float(exchange_order["cost"]),
                order_id=str(exchange_order["id"]),
                order_type="market",
                using_db=connection,
            )
            await mark_placement_persisted_in_transaction(
                preparation.operation_id,
                connection,
            )
            _kill_process()

    await _persist_execution(preparation.intent, exchange_order)
    if crash_point == "after_commit_before_cache_monitoring":
        _kill_process()
    await service.transition(
        preparation.operation_id,
        PlacementIntentState.COMPLETED,
    )


async def _recover(
    service: PlacementIntentService,
    exchange: DurableFakeExchangeAdapter,
    *,
    crash_during_lookup: bool,
) -> None:
    if crash_during_lookup:
        original_lookup = exchange.lookup_spot_order

        async def lookup_and_crash(*args: Any, **kwargs: Any) -> Any:
            await original_lookup(*args, **kwargs)
            _kill_process()

        exchange.lookup_spot_order = lookup_and_crash  # type: ignore[method-assign]

    summary = await PlacementReconciler(exchange, _resume, service).reconcile(
        LIVE_CONFIG
    )
    print(
        json.dumps(
            {
                "inspected": summary.inspected,
                "completed": summary.completed,
                "rejected": summary.rejected,
                "quarantined": summary.quarantined,
                "ready": summary.ready,
            },
            sort_keys=True,
        )
    )


async def _inspect() -> None:
    intent = await model.PlacementIntent.get_or_none(operation_id=OPERATION_ID)
    execution_count = await model.TradeExecutions.filter(deal_id=DEAL_ID).count()
    nonterminal = await model.PlacementIntent.filter(
        state__in=sorted(NONTERMINAL_PLACEMENT_STATES)
    ).all()
    pending_quote = sum(float(row.reserved_quote or 0.0) for row in nonterminal)
    quarantined_count = await model.PlacementIntent.filter(
        state__in=[
            PlacementIntentState.QUARANTINED.value,
            PlacementIntentState.RESTORED_QUARANTINED.value,
        ]
    ).count()
    print(
        json.dumps(
            {
                "intent_state": str(intent.state) if intent is not None else None,
                "execution_count": execution_count,
                "pending_quote": pending_quote,
                "quarantined_count": quarantined_count,
            },
            sort_keys=True,
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--exchange-database", type=Path, required=True)
    parser.add_argument("--exchange-script", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument(
        "--crash-point",
        choices=[
            "before_intent_commit",
            "after_intent_commit_before_submission",
            "after_exchange_acceptance_before_response",
            "after_response_before_trade_persistence",
            "during_sqlite_transaction",
            "after_commit_before_cache_monitoring",
        ],
        required=True,
    )

    recover = subparsers.add_parser("recover")
    recover.add_argument("--crash-during-lookup", action="store_true")
    subparsers.add_parser("inspect")
    return parser


async def _main() -> None:
    args = _build_parser().parse_args()
    await _initialize_database(args.database)
    try:
        service = PlacementIntentService()
        exchange = DurableFakeExchangeAdapter(
            args.exchange_script,
            args.exchange_database,
        )
        if args.command == "start":
            await _start(service, exchange, args.crash_point)
        elif args.command == "recover":
            await _recover(
                service,
                exchange,
                crash_during_lookup=args.crash_during_lookup,
            )
        else:
            await _inspect()
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(_main())
