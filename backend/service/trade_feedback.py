"""Transactional Pathfinder outbox and optional asynchronous delivery worker."""

from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

import helper
import httpx
import model
from service.signal_settings import canonicalize_signal_settings
from tortoise.exceptions import BaseORMException

logging = helper.LoggerFactory.get_logger("logs/feedback.log", "trade_feedback")


def feedback_destination(config: dict[str, Any]) -> tuple[str, dict[str, str]] | None:
    """Resolve an opted-in endpoint on the configured signal provider's origin."""
    if config.get("signal") != "websocket_signal":
        return None
    settings = canonicalize_signal_settings(config.get("signal_settings"))
    if settings.get("feedback_enabled") is not True:
        return None
    url = urlsplit(settings.get("websocket_url") or settings.get("api_url") or "")
    if (
        url.scheme not in {"ws", "wss"}
        or not url.hostname
        or url.username
        or url.password
    ):
        return None
    endpoint = urlunsplit(
        (
            "https" if url.scheme == "wss" else "http",
            url.netloc,
            "/v1/feedback/closed-trades",
            "",
            "",
        )
    )
    headers = settings.get("headers") or {}
    authorization = next(
        (
            str(value)
            for key, value in headers.items()
            if str(key).lower() == "authorization"
        ),
        "",
    )
    if not authorization:
        token = parse_qs(url.query).get("token", [""])[0]
        if token:
            authorization = f"Bearer {token}"
    return endpoint, {"Authorization": authorization} if authorization else {}


def _metadata(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _timestamp(raw: Any) -> str:
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    # Moonwalker's persisted naive close timestamps are UTC.
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def build_feedback_payload(
    summary: dict[str, Any], executions: list[Any]
) -> dict[str, Any]:
    """Build net results from ledger cash flows, never from fee-rate columns."""
    entries = [row for row in executions if row.side == "buy"]
    exits = [row for row in executions if row.side == "sell"]
    if not entries or not exits:
        raise ValueError("missing_execution_history")
    provenance = _metadata(entries[0].metadata_json).get("websocket_signal") or {}
    if not isinstance(provenance, dict) or not provenance.get("signal_id"):
        raise ValueError("missing_signal_provenance")
    execution_exchange = provenance.get("execution_exchange") or provenance.get(
        "exchange"
    )
    if str(execution_exchange).lower() != str(provenance.get("exchange")).lower():
        raise ValueError("signal_exchange_mismatch")
    source_symbol = str(provenance.get("symbol") or summary["symbol"])
    if (
        source_symbol.replace("/", "").upper()
        != str(summary["symbol"]).replace("/", "").upper()
    ):
        raise ValueError("signal_symbol_mismatch")
    buy_value = sum(float(row.ordersize) for row in entries)
    sell_value = sum(float(row.ordersize) for row in exits)
    fees = extra_buy_fees = sell_fees = 0.0
    for row in executions:
        accounting = _metadata(row.metadata_json).get("feedback_accounting")
        if not isinstance(accounting, dict) or accounting.get("complete") is not True:
            raise ValueError("incomplete_fee_accounting")
        fees += float(accounting["fees_quote"])
        extra_buy_fees += float(accounting["external_buy_fees"])
        sell_fees += float(accounting["sell_fees"])
    cost = buy_value + extra_buy_fees
    profit = sell_value - sell_fees - cost
    if cost <= 0 or not all(math.isfinite(v) for v in (cost, profit, fees)):
        raise ValueError("invalid_outcome_amounts")
    return {
        "signal_id": str(provenance["signal_id"]),
        "deal_id": str(summary["deal_id"]),
        "exchange": str(provenance.get("exchange") or ""),
        "symbol": str(summary["symbol"]),
        "opened_at": _timestamp(summary["open_date"]),
        "closed_at": _timestamp(summary["close_date"]),
        "entry_value_quote": cost,
        "net_profit_quote": profit,
        "net_return_percent": profit / cost * 100,
        "fees_quote": fees,
        "close_reason": summary.get("close_reason"),
        "execution_history_complete": bool(summary.get("execution_history_complete")),
    }


async def enqueue_feedback(
    summary: dict[str, Any], config: dict[str, Any], conn: Any
) -> None:
    """Save an immutable outcome in the same transaction as its final close."""
    destination = feedback_destination(config)
    if destination is None:
        return
    executions = (
        await model.TradeExecutions.filter(deal_id=summary["deal_id"])
        .using_db(conn)
        .order_by("id")
    )
    entry = next((row for row in executions if row.side == "buy"), None)
    provenance = (
        _metadata(entry.metadata_json).get("websocket_signal") if entry else None
    )
    if not isinstance(provenance, dict) or not provenance.get("signal_id"):
        return
    # Never send a deal to a different provider after a configuration change.
    endpoint = provenance.get("feedback_endpoint")
    if not endpoint or endpoint != destination[0]:
        return
    payload = None
    error = None
    try:
        payload = json.dumps(
            build_feedback_payload(summary, executions), sort_keys=True, allow_nan=False
        )
    except (KeyError, ValueError, TypeError, OverflowError):
        error = "incomplete_or_invalid_accounting"
        logging.warning(
            "Feedback for deal %s blocked: incomplete or invalid accounting.",
            summary["deal_id"],
        )
    await model.TradeFeedback.get_or_create(
        deal_id=str(summary["deal_id"]),
        defaults={
            "endpoint": endpoint,
            "payload_json": payload,
            "status": "blocked" if error else "pending",
            "last_error": error,
        },
        using_db=conn,
    )


async def deliver_feedback(
    row: Any, config: dict[str, Any], client: httpx.AsyncClient
) -> None:
    """Deliver one receipt without changing its payload across retries."""
    destination = feedback_destination(config)
    if destination is None or destination[0] != row.endpoint or row.status != "pending":
        return
    row.attempts += 1
    row.next_attempt_at = time.time() + min(3600, 5 * 2 ** min(row.attempts, 10))
    try:
        response = await client.post(
            row.endpoint,
            content=row.payload_json,
            headers={**destination[1], "Content-Type": "application/json"},
        )
        if 200 <= response.status_code < 300:
            try:
                acknowledgement = response.json()
                payload = json.loads(row.payload_json)
                accepted = (
                    isinstance(acknowledgement, dict)
                    and acknowledgement.get("accepted") is True
                    and acknowledgement.get("deal_id") == row.deal_id
                    and acknowledgement.get("signal_id") == payload["signal_id"]
                )
            except (ValueError, TypeError):
                accepted = False
            if accepted:
                row.status = "sent"
                row.last_error = None
            else:
                row.last_error = "invalid_acknowledgement"
        elif response.status_code == 429 or response.status_code >= 500:
            row.last_error = f"http_{response.status_code}"
        else:
            row.status = "rejected"
            row.last_error = f"http_{response.status_code}"
    except httpx.HTTPError:
        # URLs, headers, and response bodies may contain credentials.
        row.last_error = "transport_error"
    await row.save()
    if row.status == "rejected":
        logging.warning(
            "Feedback for deal %s rejected (%s).", row.deal_id, row.last_error
        )


async def run_feedback_worker() -> None:
    """Drain bounded outbox batches; disabled configuration pauses delivery."""
    from service.config import Config

    config = await Config.instance()
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        while True:
            try:
                destination = feedback_destination(config.snapshot())
                if destination is not None:
                    rows = (
                        await model.TradeFeedback.filter(
                            status="pending",
                            endpoint=destination[0],
                            next_attempt_at__lte=time.time(),
                        )
                        .order_by("id")
                        .limit(25)
                    )
                    for row in rows:
                        await deliver_feedback(row, config.snapshot(), client)
            except (BaseORMException, ValueError, TypeError, OSError):
                logging.warning("Feedback delivery temporarily unavailable; retrying.")
            await asyncio.sleep(5)
