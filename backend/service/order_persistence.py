"""Transactional persistence helpers for order workflows."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import model
from service.database import run_sqlite_write_with_retry
from service.replay_candles import archive_replay_candles_for_deal
from tortoise.transactions import in_transaction

SUMMARY_TRADE_KEYS = {
    "symbol",
    "deal_id",
    "execution_history_complete",
    "so_count",
    "profit",
    "profit_percent",
    "amount",
    "cost",
    "tp_price",
    "avg_price",
    "open_date",
    "close_date",
    "duration",
}


def _create_deal_id() -> str:
    """Return a fresh stable deal identifier."""
    return str(uuid4())


def _resolve_buy_execution_role(payload: dict[str, Any]) -> str:
    """Return the ledger role for a persisted buy row."""
    if bool(payload.get("baseorder")):
        return "base_order"
    if str(payload.get("orderid") or "").startswith("manual-add-"):
        return "manual_buy"
    if bool(payload.get("safetyorder")):
        return "safety_order"
    return "buy"


def _build_trade_execution_payload(
    deal_id: str,
    payload: dict[str, Any],
    *,
    role: str,
) -> dict[str, Any]:
    """Normalize a trade-row payload into a TradeExecutions insert payload."""
    return {
        "deal_id": deal_id,
        "symbol": str(payload.get("symbol") or ""),
        "side": str(payload.get("side") or "buy"),
        "role": role,
        "timestamp": str(payload.get("timestamp") or ""),
        "price": float(payload.get("price") or 0.0),
        "amount": float(payload.get("amount") or payload.get("total_amount") or 0.0),
        "ordersize": float(payload.get("ordersize") or 0.0),
        "fee": float(payload.get("fee") or 0.0),
        "order_id": (
            str(payload.get("order_id") or payload.get("orderid"))
            if payload.get("order_id") is not None or payload.get("orderid") is not None
            else None
        ),
        "order_type": (
            str(payload.get("order_type") or payload.get("ordertype"))
            if payload.get("order_type") is not None
            or payload.get("ordertype") is not None
            else None
        ),
        "order_count": payload.get("order_count"),
        "so_percentage": (
            float(payload["so_percentage"])
            if payload.get("so_percentage") is not None
            else None
        ),
        "signal_name": (
            str(payload.get("signal_name"))
            if payload.get("signal_name") is not None
            else None
        ),
        "strategy_name": (
            str(payload.get("strategy_name"))
            if payload.get("strategy_name") is not None
            else None
        ),
        "timeframe": (
            str(payload.get("timeframe"))
            if payload.get("timeframe") is not None
            else None
        ),
        "metadata_json": (
            str(payload.get("metadata_json"))
            if payload.get("metadata_json") is not None
            else None
        ),
    }


async def _resolve_open_deal_state(symbol: str, conn: Any) -> tuple[str, bool]:
    """Return the open deal id and replay completeness flag for a symbol."""
    open_trade = await model.OpenTrades.filter(symbol=symbol).using_db(conn).first()
    if open_trade is None:
        return _create_deal_id(), True

    deal_id = open_trade.deal_id or _create_deal_id()
    if open_trade.deal_id != deal_id:
        await model.OpenTrades.filter(symbol=symbol).using_db(conn).update(
            deal_id=deal_id,
        )
    return deal_id, bool(open_trade.execution_history_complete)


async def persist_buy_trade(
    symbol: str,
    payload: dict[str, Any],
    *,
    create_open_trade: bool,
) -> None:
    """Persist a filled buy trade and create the open-trade row when needed."""

    async def _persist_buy() -> None:
        async with in_transaction() as conn:
            if create_open_trade:
                deal_id = str(payload.get("deal_id") or _create_deal_id())
                history_complete = True
            else:
                deal_id, history_complete = await _resolve_open_deal_state(symbol, conn)

            payload["deal_id"] = deal_id
            await model.Trades.create(**payload, using_db=conn)
            await model.TradeExecutions.create(
                **_build_trade_execution_payload(
                    deal_id,
                    payload,
                    role=_resolve_buy_execution_role(payload),
                ),
                using_db=conn,
            )
            if create_open_trade:
                await model.OpenTrades.create(
                    symbol=symbol,
                    deal_id=deal_id,
                    execution_history_complete=history_complete,
                    using_db=conn,
                )

    await run_sqlite_write_with_retry(
        _persist_buy, f"persisting buy order for {symbol}"
    )


async def persist_closed_trade(symbol: str, payload: dict[str, Any]) -> None:
    """Persist a closed trade and remove its open-trade rows."""

    async def _persist_sell() -> None:
        async with in_transaction() as conn:
            deal_id, history_complete = await _resolve_open_deal_state(symbol, conn)
            summary_payload = {
                key: value
                for key, value in payload.items()
                if key in SUMMARY_TRADE_KEYS
            }
            summary_payload["deal_id"] = deal_id
            summary_payload["execution_history_complete"] = history_complete
            await model.ClosedTrades.create(**summary_payload, using_db=conn)

            for sell_execution in payload.get("sell_executions") or []:
                if not isinstance(sell_execution, dict):
                    continue
                if float(sell_execution.get("amount") or 0.0) <= 0:
                    continue
                await model.TradeExecutions.create(
                    **_build_trade_execution_payload(
                        deal_id,
                        sell_execution,
                        role=str(sell_execution.get("role") or "final_sell"),
                    ),
                    using_db=conn,
                )
            await archive_replay_candles_for_deal(
                deal_id,
                symbol,
                open_date=summary_payload.get("open_date"),
                close_date=summary_payload.get("close_date"),
                conn=conn,
            )
            await model.Trades.filter(symbol=symbol).using_db(conn).delete()
            await model.OpenTrades.filter(symbol=symbol).using_db(conn).delete()

    await run_sqlite_write_with_retry(
        _persist_sell, f"persisting sell order for {symbol}"
    )


async def persist_manual_buy_add(
    symbol: str,
    trade_payload: dict[str, Any],
    open_trade_payload: dict[str, Any],
) -> None:
    """Persist a manual buy add and update the matching open trade."""

    async def _persist_manual_buy() -> None:
        async with in_transaction() as conn:
            deal_id, history_complete = await _resolve_open_deal_state(symbol, conn)
            trade_payload["deal_id"] = deal_id
            await model.Trades.create(**trade_payload, using_db=conn)
            await model.TradeExecutions.create(
                **_build_trade_execution_payload(
                    deal_id,
                    trade_payload,
                    role=_resolve_buy_execution_role(trade_payload),
                ),
                using_db=conn,
            )
            open_trade_payload["deal_id"] = deal_id
            open_trade_payload["execution_history_complete"] = history_complete
            updated = (
                await model.OpenTrades.filter(symbol=symbol)
                .using_db(conn)
                .update(**open_trade_payload)
            )
            if updated == 0:
                raise ValueError(f"No open trade found for {symbol}.")

    await run_sqlite_write_with_retry(
        _persist_manual_buy, f"persisting manual buy add for {symbol}"
    )


async def persist_unsellable_remainder(
    symbol: str,
    payload: dict[str, Any],
) -> None:
    """Persist an unsellable remainder archive and remove open-trade rows."""

    async def _persist_unsellable_remainder() -> None:
        async with in_transaction() as conn:
            deal_id, history_complete = await _resolve_open_deal_state(symbol, conn)
            summary_payload = dict(payload)
            summary_payload["deal_id"] = deal_id
            summary_payload["execution_history_complete"] = history_complete
            await model.UnsellableTrades.create(**summary_payload, using_db=conn)
            await model.Trades.filter(symbol=symbol).using_db(conn).delete()
            await model.OpenTrades.filter(symbol=symbol).using_db(conn).delete()

    await run_sqlite_write_with_retry(
        _persist_unsellable_remainder,
        f"persisting unsellable remainder for {symbol}",
    )


async def persist_stopped_trade(symbol: str) -> None:
    """Delete open-trade state for a stopped symbol."""

    async def _persist_stop() -> None:
        async with in_transaction() as conn:
            open_trade = (
                await model.OpenTrades.filter(symbol=symbol).using_db(conn).first()
            )
            await model.OpenTrades.filter(symbol=symbol).using_db(conn).delete()
            await model.Trades.filter(symbol=symbol).using_db(conn).delete()
            if open_trade and open_trade.deal_id:
                await model.TradeExecutions.filter(
                    deal_id=open_trade.deal_id,
                ).using_db(conn).delete()

    await run_sqlite_write_with_retry(_persist_stop, f"stopping symbol {symbol}")
