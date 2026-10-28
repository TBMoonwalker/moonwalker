"""Bounded accumulation activity pages with mutation-aware cursors."""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
import uuid
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from service.accumulation.imports import AccumulationImport
from service.accumulation.reporting import _amount, _fees
from tortoise.transactions import in_transaction

_PROCESS = uuid.uuid4().hex
_SECRET = secrets.token_bytes(32)
_CURSOR_LIFETIME = 300
_PAGE_SIZE = 20


class ActivityChanged(ValueError):
    """The requested activity snapshot expired or changed."""


def _price_per_coin(quantity: Any, quote_cost: Any) -> str | None:
    """Divide recorded quote by quantity without converting through floats."""
    quantity_text = _amount(quantity)
    cost_text = _amount(quote_cost)
    if quantity_text is None or cost_text is None:
        return None
    try:
        amount = Decimal(quantity_text)
        cost = Decimal(cost_text)
        if amount <= 0 or cost <= 0:
            return None
        with localcontext() as context:
            context.prec = 512
            return format(cost / amount, "f")
    except (InvalidOperation, ValueError):
        return None


def _encode(value: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    signature = hmac.new(_SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _decode(value: str) -> dict[str, Any]:
    try:
        if len(value) > 1024:
            raise ValueError
        body, signature = value.split(".", 1)
        expected = hmac.new(_SECRET, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ActivityChanged("Activity snapshot expired. Restart the history.")
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError
        if (
            not isinstance(result.get("process"), str)
            or not isinstance(result.get("scope"), str)
            or type(result.get("revision")) is not int
            or type(result.get("expires")) is not int
            or not isinstance(result.get("updated_at"), str)
            or result.get("kind") not in ("order", "csv")
            or type(result.get("id")) is not int
        ):
            raise ValueError
        if result["process"] != _PROCESS:
            raise ActivityChanged("Activity snapshot expired. Restart the history.")
        if result["expires"] < int(time.time()):
            raise ActivityChanged("Activity snapshot expired. Restart the history.")
        return result
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        if isinstance(exc, ActivityChanged):
            raise
        raise ValueError("Invalid activity cursor.") from exc


def _project(row: dict[str, Any], account_scope: str) -> dict[str, Any]:
    common = {
        "kind": row["kind"],
        "id": row["id"],
        "updated_at": row["updated_at"],
        "symbol": row["symbol"],
        "deal_id": row["deal_id"],
    }
    if row["kind"] == "order":
        try:
            fees = _fees(json.loads(row["fees_json"]))
        except (ValueError, TypeError):
            fees = None
        return {
            **common,
            "side": row["side"],
            "quantity": _amount(row["filled"]),
            "quote_cost": _amount(row["quote_cost"]),
            "price_per_coin": _price_per_coin(row["filled"], row["quote_cost"]),
            "fees": fees,
            "fees_complete": bool(row["fees_complete"]) and fees is not None,
            "terminal": bool(row["terminal"]),
        }
    try:
        request = json.loads(row["request_json"])
        deal_id = str(uuid.UUID(request["_csv_deal_id"]))
        declaration = AccumulationImport.from_dict(request["imported_inventory"])
        if (
            request["source"] != "csv"
            or request["account_scope"] != account_scope
            or declaration.symbol != row["symbol"]
        ):
            raise ValueError
        inventory = declaration.inventory()
        return {
            **common,
            "deal_id": deal_id,
            "quantity": inventory.quantity,
            "quote_cost": inventory.remaining_cost,
            "price_per_coin": _price_per_coin(
                inventory.quantity, inventory.remaining_cost
            ),
            "fees": inventory.fees,
            "fees_complete": inventory.pending_fee_reports == 0,
            "declaration_complete": True,
        }
    except (ValueError, TypeError, KeyError, AttributeError):
        return {**common, "declaration_complete": False}


async def activity_page(
    account_scope: str, cursor: str | None = None
) -> dict[str, Any]:
    """Return one consistent page of cumulative orders and CSV declarations."""
    if not account_scope:
        raise ValueError("An active account scope is required for activity history.")
    position = _decode(cursor) if cursor else None
    scope_token = hashlib.sha256(account_scope.encode()).hexdigest()
    if position and position["scope"] != scope_token:
        raise ActivityChanged("Account changed. Restart the history.")
    async with in_transaction() as conn:
        revisions = await conn.execute_query_dict(
            "SELECT revision FROM accumulation_history_revision WHERE id = 1"
        )
        if len(revisions) != 1:
            raise ValueError("Activity history is unavailable.")
        revision = revisions[0]["revision"]
        if position and position["revision"] != revision:
            raise ActivityChanged("Activity changed. Restart the history.")
        where = ""
        values: list[Any] = [account_scope, account_scope]
        if position:
            where = (
                "WHERE (updated_at < ? OR (updated_at = ? AND kind < ?) OR "
                "(updated_at = ? AND kind = ? AND id < ?))"
            )
            values.extend(
                [
                    position["updated_at"],
                    position["updated_at"],
                    position["kind"],
                    position["updated_at"],
                    position["kind"],
                    position["id"],
                ]
            )
        values.append(_PAGE_SIZE + 1)
        rows = await conn.execute_query_dict(
            """
            SELECT * FROM (
              SELECT 'order' AS kind, c.id, c.updated_at, a.symbol, c.deal_id,
                c.filled, c.quote_cost, c.fees_json, c.fees_complete, c.terminal,
                p.side, NULL AS request_json
              FROM accumulation_fill_checkpoints c
              JOIN accumulation_activations a ON a.id = c.activation_id
              JOIN placement_intents p ON p.id = c.placement_id
              WHERE a.account_scope = ? AND c.filled != '0'
              UNION ALL
              SELECT 'csv' AS kind, o.id, o.updated_at, a.symbol, NULL AS deal_id,
                NULL, NULL, NULL, NULL, NULL, NULL, o.request_json
              FROM accumulation_lifecycle_operations o
              JOIN accumulation_activations a ON a.id = o.activation_id
              WHERE a.account_scope = ? AND o.status = 'applied'
                AND o.action IN ('activate', 'retry_entry', 'correct_import')
                AND o.request_json LIKE '%"_csv_deal_id"%'
            ) AS activity
            """
            + where
            + " ORDER BY updated_at DESC, kind DESC, id DESC LIMIT ?",
            values,
        )
    page = rows[:_PAGE_SIZE]
    next_cursor = None
    if len(rows) > _PAGE_SIZE:
        last = page[-1]
        next_cursor = _encode(
            {
                "process": _PROCESS,
                "scope": scope_token,
                "revision": revision,
                "expires": position["expires"]
                if position
                else int(time.time()) + _CURSOR_LIFETIME,
                "updated_at": str(last["updated_at"]),
                "kind": last["kind"],
                "id": last["id"],
            }
        )
    return {
        "items": [_project(row, account_scope) for row in page],
        "next_cursor": next_cursor,
    }
