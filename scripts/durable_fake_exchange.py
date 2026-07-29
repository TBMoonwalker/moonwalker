#!/usr/bin/env python3
"""Process-independent fake exchange with a durable client-order-id ledger."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def _connect(database_path: Path) -> sqlite3.Connection:
    """Open the durable fake-exchange store and ensure its schema exists."""
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS exchange_orders (
            client_order_id TEXT PRIMARY KEY,
            exchange_order_id TEXT NOT NULL UNIQUE,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            status TEXT NOT NULL,
            amount REAL NOT NULL,
            price REAL NOT NULL,
            submit_attempts INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    connection.commit()
    return connection


def _order_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Convert one fake exchange row into the CCXT-shaped lookup contract."""
    amount = float(row["amount"])
    return {
        "id": str(row["exchange_order_id"]),
        "clientOrderId": str(row["client_order_id"]),
        "symbol": str(row["symbol"]),
        "side": str(row["side"]),
        "status": str(row["status"]),
        "amount": amount,
        "filled": amount,
        "remaining": 0.0,
        "price": float(row["price"]),
        "average": float(row["price"]),
        "cost": round(amount * float(row["price"]), 8),
        "timestamp": 1_780_000_000_000,
    }


def submit_order(
    database_path: Path,
    *,
    client_order_id: str,
    symbol: str,
    side: str,
    amount: float,
    price: float,
) -> dict[str, Any]:
    """Idempotently accept one order identified by its client order id."""
    connection = _connect(database_path)
    try:
        exchange_order_id = f"fake-{client_order_id}"
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO exchange_orders (
                client_order_id,
                exchange_order_id,
                symbol,
                side,
                status,
                amount,
                price
            )
            VALUES (?, ?, ?, ?, 'closed', ?, ?)
            """,
            (
                client_order_id,
                exchange_order_id,
                symbol,
                side,
                amount,
                price,
            ),
        )
        if cursor.rowcount == 0:
            connection.execute(
                """
                UPDATE exchange_orders
                SET submit_attempts = submit_attempts + 1
                WHERE client_order_id = ?
                """,
                (client_order_id,),
            )
        connection.commit()
        row = connection.execute(
            """
            SELECT *
            FROM exchange_orders
            WHERE client_order_id = ?
            """,
            (client_order_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Fake exchange failed to persist the accepted order")
        return _order_payload(row)
    finally:
        connection.close()


def lookup_order(
    database_path: Path,
    *,
    client_order_id: str,
) -> dict[str, Any] | None:
    """Look up an accepted order by its stable client identity."""
    connection = _connect(database_path)
    try:
        row = connection.execute(
            """
            SELECT *
            FROM exchange_orders
            WHERE client_order_id = ?
            """,
            (client_order_id,),
        ).fetchone()
        return _order_payload(row) if row is not None else None
    finally:
        connection.close()


def exchange_summary(database_path: Path) -> dict[str, int]:
    """Return durable exchange counts used by the crash-recovery assertions."""
    connection = _connect(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS order_count,
                COALESCE(SUM(submit_attempts), 0) AS submit_attempts
            FROM exchange_orders
            """
        ).fetchone()
        return {
            "order_count": int(row["order_count"]),
            "submit_attempts": int(row["submit_attempts"]),
        }
    finally:
        connection.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser("submit")
    submit.add_argument("--client-order-id", required=True)
    submit.add_argument("--symbol", required=True)
    submit.add_argument("--side", required=True)
    submit.add_argument("--amount", type=float, required=True)
    submit.add_argument("--price", type=float, required=True)

    lookup = subparsers.add_parser("lookup")
    lookup.add_argument("--client-order-id", required=True)

    subparsers.add_parser("summary")
    return parser


def main() -> None:
    """Run one fake-exchange operation and emit its JSON response."""
    args = _build_parser().parse_args()
    if args.command == "submit":
        result = submit_order(
            args.database,
            client_order_id=args.client_order_id,
            symbol=args.symbol,
            side=args.side,
            amount=args.amount,
            price=args.price,
        )
    elif args.command == "lookup":
        result = lookup_order(
            args.database,
            client_order_id=args.client_order_id,
        )
    else:
        result = exchange_summary(args.database)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
