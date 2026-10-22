"""Accumulation projections, isolated replay and revisioned operator commands."""

from dataclasses import asdict
from typing import Any

from controller.responses import json_response
from litestar.connection import Request
from litestar.exceptions import SerializationException
from litestar.handlers import get, post
from litestar.params import FromQuery
from service import accumulation_runtime
from service.accumulation_catalog import (
    create_accumulation_strategy,
    list_accumulation_strategies,
)
from service.accumulation_runtime import AccumulationRuntime
from service.accumulation_state import AccumulationConflictError
from service.accumulation_status import (
    get_accumulation_status,
    list_accumulation_status,
)
from service.runtime_services import get_active_accumulation_runtime


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
        return await list_accumulation_status(
            limit=limit,
            after=after,
            wait_reasons=dict(runtime.status),
            configured_account_scope=getattr(runtime, "current_account_scope", None),
        )
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
    """List compatible versions, ensuring the built-in setup starter exists."""
    if _runtime(repair=True) is None:
        return _unavailable()
    try:
        return await list_accumulation_strategies(after_id=after_id, limit=limit)
    except ValueError as exc:
        return json_response({"error": str(exc), "code": "invalid_request"}, 400)


@post(path="/accumulation/strategies", status_code=200)
async def create_strategy(request: Request[Any, Any, Any]) -> Any:
    """Save a validated immutable variant; never rebind an activation."""
    if _runtime() is None:
        return _unavailable()
    try:
        payload = await request.json()
        return await create_accumulation_strategy(payload)
    except AccumulationConflictError as exc:
        return json_response({"error": str(exc), "code": "conflict"}, 409)
    except (SerializationException, ValueError) as exc:
        return json_response({"error": str(exc), "code": "invalid_request"}, 400)


@get(path="/accumulation/performance")
async def get_performance() -> Any:
    """Value exact managed inventory with fresh bid marks and explicit coverage."""
    runtime = _runtime()
    if runtime is None:
        return _unavailable()
    return await runtime.performance()


route_handlers = [
    get_performance,
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
    from service.accumulation_replay import run_accumulation_replay
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
