"""Accumulation projections, isolated replay and revisioned operator commands."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import asdict
from typing import Any

from controller.responses import json_response
from litestar.connection import Request
from litestar.exceptions import SerializationException, WebSocketDisconnect
from litestar.handlers import get, post, websocket_stream
from litestar.params import FromQuery
from service.accumulation import runtime as accumulation_runtime
from service.accumulation.activity import ActivityChanged, activity_page
from service.accumulation.catalog import list_accumulation_strategies
from service.accumulation.runtime import AccumulationRuntime
from service.accumulation.state import AccumulationConflictError
from service.accumulation.status import (
    accumulation_stream_snapshot,
    get_accumulation_status,
    list_accumulation_status,
)
from service.runtime_services import get_active_accumulation_runtime
from tortoise import Tortoise
from tortoise.exceptions import OperationalError


def _runtime(*, repair: bool = False) -> AccumulationRuntime | None:
    # Check before resolving services or credentials, even if rows were restored.
    if not accumulation_runtime.ACCUMULATION_RUNTIME_AVAILABLE:
        return None
    runtime = get_active_accumulation_runtime()
    return (
        runtime
        if runtime is not None
        and (runtime.ready or repair and getattr(runtime, "repair_ready", False))
        else None
    )


def _unavailable() -> Any:
    return json_response(
        {"error": "Accumulation is unavailable.", "code": "unavailable"}, 503
    )


@get(path="/accumulation/activations")
async def list_activations(
    limit: FromQuery[int] = 50, after: FromQuery[str | None] = None
) -> Any:
    """Return at most 100 registry rows, including zero-inventory and stopped entries."""
    runtime = _runtime(repair=True)
    if runtime is None:
        return _unavailable()
    try:
        result = await list_accumulation_status(
            limit=limit,
            after=after,
            wait_reasons=dict(runtime.status),
            configured_account_scope=getattr(runtime, "current_account_scope", None),
            wait_conditions=getattr(runtime, "wait_conditions", {}),
        )
        return {**result, "stream_available": runtime.ready}
    except ValueError as exc:
        return json_response({"error": str(exc), "code": "invalid_request"}, 400)


@get(path="/accumulation/activation")
async def get_activation(symbol: FromQuery[str]) -> Any:
    """Return an exact current snapshot and recent historical operation outcomes."""
    runtime = _runtime(repair=True)
    if runtime is None:
        return _unavailable()
    try:
        result = await get_accumulation_status(
            symbol,
            wait_reasons=dict(runtime.status),
            configured_account_scope=getattr(runtime, "current_account_scope", None),
            wait_conditions=getattr(runtime, "wait_conditions", {}),
        )
    except ValueError as exc:
        return json_response({"error": str(exc), "code": "invalid_request"}, 400)
    return (
        result
        if result is not None
        else json_response({"error": "Activation not found."}, 404)
    )


async def _submit(
    request: Request[Any, Any, Any], *, staged: bool, repair: bool = False
) -> Any:
    runtime = _runtime(repair=repair)
    if runtime is None:
        return _unavailable()
    try:
        payload = await request.json()
    except SerializationException:
        return json_response({"error": "Payload must be a JSON object."}, 400)
    if not isinstance(payload, dict):
        return json_response({"error": "Payload must be a JSON object."}, 400)
    if not runtime.ready and payload.get("action") not in {
        "repair_order",
        "retire_command",
        "acknowledge_settlement",
    }:
        return json_response(
            {
                "error": "Only order reconciliation and interrupted-command retirement are available. Restart after repair before trading.",
                "code": "recovery_only",
            },
            409,
        )
    try:
        result = (
            await runtime.repairs.submit(payload)
            if repair
            else await runtime.entry.submit_staged(payload)
            if staged
            else await runtime.submit_command(payload)
        )
    except AccumulationConflictError as exc:
        return json_response({"error": str(exc), "code": "conflict"}, 409)
    except ValueError as exc:
        return json_response({"error": str(exc), "code": "invalid_request"}, 400)
    if runtime.ready:
        runtime.notify()
    runtime.status_events.publish()
    return json_response(
        {"operation": asdict(result)},
        202 if result.status in {"pending", "quarantined"} else 200,
    )


@post(path="/accumulation/commands", status_code=200)
async def submit_command(request: Request[Any, Any, Any]) -> Any:
    """Journal lifecycle intent; return 202 while the runtime owns pending work."""
    return await _submit(request, staged=False)


@post(path="/accumulation/entry/commands", status_code=200)
async def submit_entry_command(request: Request[Any, Any, Any]) -> Any:
    """Correct, abandon or freshly validate a revisioned staged entry."""
    return await _submit(request, staged=True)


@post(path="/accumulation/repair", status_code=200)
async def submit_repair(request: Request[Any, Any, Any]) -> Any:
    """Explicitly look up one quarantined order; never place or cancel an order."""
    return await _submit(request, staged=False, repair=True)


@get(path="/accumulation/strategies")
async def list_strategies(
    after_id: FromQuery[int] = 0, limit: FromQuery[int] = 50
) -> Any:
    """List compatible shared versions; retired dip presets stay out of selectors."""
    runtime = _runtime(repair=True)
    if runtime is None:
        return _unavailable()
    try:
        return await list_accumulation_strategies(
            after_id=after_id,
            limit=limit,
            timeframe=runtime.adapter.config_provider().get("timeframe"),
        )
    except ValueError as exc:
        return json_response({"error": str(exc), "code": "invalid_request"}, 400)


@post(path="/accumulation/strategies", status_code=200)
async def create_strategy() -> Any:
    """Reject the retired standalone preset writer; use the shared builder."""
    if _runtime() is None:
        return _unavailable()
    return json_response(
        {
            "error": "Standalone accumulation dip presets are retired. Use Strategy Builder.",
            "code": "retired_strategy_writer",
        },
        410,
    )


@get(path="/accumulation/performance")
async def get_performance() -> Any:
    """Value exact managed inventory with fresh bid marks and explicit coverage."""
    runtime = _runtime()
    if runtime is None:
        return _unavailable()
    return await runtime.performance()


@get(path="/accumulation/activity")
async def get_activity(cursor: FromQuery[str | None] = None) -> Any:
    """Return a stable page of cumulative orders and declared CSV imports."""
    runtime = _runtime()
    if runtime is None:
        return _unavailable()
    try:
        return await activity_page(
            getattr(runtime, "current_account_scope", ""), cursor
        )
    except ActivityChanged as exc:
        return json_response({"error": str(exc), "code": "activity_changed"}, 409)
    except ValueError as exc:
        return json_response({"error": str(exc), "code": "invalid_request"}, 400)
    except OperationalError:
        return json_response(
            {"error": "Activity history is unavailable.", "code": "unavailable"}, 503
        )


@websocket_stream(path="/accumulation/performance/stream", warn_on_data_discard=False)
async def stream_performance() -> AsyncGenerator[str, None]:
    """Push shared valuation snapshots and the activity revision to clients."""
    failure_logged = False
    last_scope: str | None = None
    scope_initialized = False
    account_generation = 0
    try:
        while True:
            runtime = _runtime()
            if runtime is None:
                yield json.dumps({"type": "unavailable"})
                return
            try:
                performance = await runtime.performance()
                scope = getattr(runtime, "current_account_scope", None)
                if scope_initialized and scope != last_scope:
                    account_generation += 1
                last_scope = scope
                scope_initialized = True
                try:
                    rows = await Tortoise.get_connection("default").execute_query_dict(
                        "SELECT revision FROM accumulation_history_revision WHERE id = 1"
                    )
                    revision = rows[0]["revision"] if rows else None
                except OperationalError:
                    revision = None
                yield json.dumps(
                    {
                        "type": "snapshot",
                        "performance": performance,
                        "activity_revision": revision,
                        "account_generation": account_generation,
                    }
                )
                failure_logged = False
            except Exception:  # noqa: BLE001 - isolate transient stream failures.
                if not failure_logged:
                    logging.getLogger(__name__).exception(
                        "Accumulation performance stream failed"
                    )
                    failure_logged = True
                yield json.dumps({"type": "unavailable"})
            await asyncio.sleep(2)
    except (asyncio.CancelledError, WebSocketDisconnect):
        return


@websocket_stream(path="/accumulation/stream", warn_on_data_discard=False)
async def stream_status(
    symbol: FromQuery[str | None] = None,
) -> AsyncGenerator[str, None]:
    """Send an initial snapshot, then only changed runtime/lifecycle snapshots."""
    runtime = _runtime()
    if runtime is None:
        yield json.dumps({"type": "unavailable"})
        return
    if symbol is not None:
        from service.order_requests import normalize_order_symbol

        symbol = normalize_order_symbol(symbol)
    previous: str | None = None
    try:
        async with aclosing(runtime.status_events.subscribe()) as updates:
            async for _ in updates:
                reasons = dict(runtime.status)
                now_ms = time.time_ns() // 1_000_000
                conditions = {
                    name: condition
                    for name, condition in runtime.wait_conditions.items()
                    if condition["observed_close_ms"]
                    <= now_ms
                    < condition["next_close_ms"]
                }
                scope = runtime.current_account_scope
                key = json.dumps([symbol, scope, reasons, conditions], sort_keys=True)

                async def produce() -> str:
                    return json.dumps(
                        await accumulation_stream_snapshot(
                            symbol,
                            wait_reasons=reasons,
                            wait_conditions=conditions,
                            configured_account_scope=scope,
                        )
                    )

                payload = await runtime.status_events.projections.read(key, produce)
                if payload != previous:
                    previous = payload
                    yield payload
    except (asyncio.CancelledError, WebSocketDisconnect):
        return


route_handlers = [
    stream_status,
    stream_performance,
    get_performance,
    get_activity,
    list_activations,
    get_activation,
    submit_command,
    submit_entry_command,
    submit_repair,
    list_strategies,
    create_strategy,
]


@post(path="/accumulation/replay", status_code=200)
async def replay_strategy(request: Request[Any, Any, Any]) -> Any:
    """Run an isolated, bounded historical comparison without account actions."""
    if _runtime() is None:
        return _unavailable()
    from service.accumulation.replay import run_accumulation_replay
    from service.strategy_runtime import load_accumulation_strategy_version

    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("Replay requires an object.")
        version_id = payload.get("strategy_version_id")
        if type(version_id) is not int or version_id < 1:
            raise ValueError("Select a compatible strategy version.")
        version = await load_accumulation_strategy_version(version_id)
        # CPU-bound, bounded simulation must not block market/runtime I/O.
        import asyncio

        result = await asyncio.to_thread(
            run_accumulation_replay,
            {
                key: value
                for key, value in payload.items()
                if key != "strategy_version_id"
            },
            version.parameters,
        )
        return {**result, "strategy_version_id": version_id}
    except AccumulationConflictError as exc:
        return json_response({"error": str(exc), "code": "conflict"}, 409)
    except (SerializationException, ValueError) as exc:
        return json_response({"error": str(exc), "code": "invalid_request"}, 400)


route_handlers.append(replay_strategy)
