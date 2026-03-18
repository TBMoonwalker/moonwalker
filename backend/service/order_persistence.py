"""Transactional persistence helpers for order workflows."""

from __future__ import annotations

from typing import Any

import model
from service.database import run_sqlite_write_with_retry
from tortoise.transactions import in_transaction


async def persist_buy_trade(
    symbol: str,
    payload: dict[str, Any],
    *,
    create_open_trade: bool,
) -> None:
    """Persist a filled buy trade and create the open-trade row when needed."""

    async def _persist_buy() -> None:
        async with in_transaction() as conn:
            await model.Trades.create(**payload, using_db=conn)
            if create_open_trade:
                await model.OpenTrades.create(symbol=symbol, using_db=conn)

    await run_sqlite_write_with_retry(
        _persist_buy, f"persisting buy order for {symbol}"
    )


async def persist_closed_trade(symbol: str, payload: dict[str, Any]) -> None:
    """Persist a closed trade and remove its open-trade rows."""

    async def _persist_sell() -> None:
        async with in_transaction() as conn:
            await model.ClosedTrades.create(**payload, using_db=conn)
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
            await model.Trades.create(**trade_payload, using_db=conn)
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
            await model.UnsellableTrades.create(**payload, using_db=conn)
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
            await model.OpenTrades.filter(symbol=symbol).using_db(conn).delete()
            await model.Trades.filter(symbol=symbol).using_db(conn).delete()

    await run_sqlite_write_with_retry(_persist_stop, f"stopping symbol {symbol}")
