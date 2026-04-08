"""Queue and backpressure helpers for watcher runtime workers."""

from __future__ import annotations

import asyncio
from typing import Any


def summarize_worker_tasks(worker_tasks: list[asyncio.Task]) -> str:
    """Return a compact summary of worker liveness for overflow logs."""
    return ", ".join(
        f"{task.get_name()}={'done' if task.done() else 'alive'}"
        for task in worker_tasks
    )


def queue_dca_payload(
    payload: dict[str, Any],
    *,
    queue: asyncio.Queue[str],
    pending_payloads: dict[str, dict[str, Any]],
    queued_symbols: set[str],
    worker_tasks: list[asyncio.Task],
    logger: Any,
) -> None:
    """Keep only the newest queued DCA payload per symbol."""
    ticker = payload.get("ticker")
    symbol = ticker.get("symbol") if isinstance(ticker, dict) else None
    if not isinstance(symbol, str) or not symbol:
        logger.warning("Skipping invalid DCA payload without symbol: %s", payload)
        return

    pending_payloads[symbol] = payload
    if symbol in queued_symbols:
        return

    try:
        queue.put_nowait(symbol)
        queued_symbols.add(symbol)
    except asyncio.QueueFull:
        pending_payloads.pop(symbol, None)
        logger.warning(
            "dca queue full; dropping event for %s. qsize=%s workers=[%s]",
            symbol,
            queue.qsize(),
            summarize_worker_tasks(worker_tasks) or "none",
        )


def queue_bounded_payload(
    queue: asyncio.Queue[Any],
    payload: Any,
    *,
    name: str,
    worker_tasks: list[asyncio.Task],
    logger: Any,
) -> None:
    """Queue a bounded payload and log when overflow forces a drop."""
    try:
        queue.put_nowait(payload)
    except asyncio.QueueFull:
        logger.warning(
            "%s queue full; dropping event. qsize=%s workers=[%s]",
            name,
            queue.qsize(),
            summarize_worker_tasks(worker_tasks) or "none",
        )


def pop_pending_dca_payload(
    symbol: str,
    *,
    pending_payloads: dict[str, dict[str, Any]],
    queued_symbols: set[str],
) -> dict[str, Any] | None:
    """Return and clear the latest queued DCA payload for a symbol."""
    queued_symbols.discard(symbol)
    return pending_payloads.pop(symbol, None)
