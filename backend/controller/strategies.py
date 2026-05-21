"""Strategy Builder API endpoints."""

from typing import Any

from controller.responses import json_response
from litestar.handlers import delete, get, post, put
from service.strategy_builder import (
    create_blank_strategy,
    delete_custom_strategy,
    duplicate_strategy,
    get_strategy_detail,
    list_strategy_summaries,
    promote_strategy_version,
    validate_strategy_ir,
)


@get(path="/strategies")
async def list_strategies() -> dict[str, Any]:
    """Return Strategy Builder summaries and node palette metadata."""
    strategies = await list_strategy_summaries()
    detail = await get_strategy_detail(strategies[0]["slug"]) if strategies else None
    return {
        "strategies": strategies,
        "palette": detail.get("palette", []) if detail else [],
    }


@get(path="/strategies/{slug:str}")
async def get_strategy(slug: str) -> Any:
    """Return one Strategy Builder definition."""
    detail = await get_strategy_detail(slug)
    if detail is None:
        return json_response({"error": "Strategy not found"}, 404)
    return detail


@post(path="/strategies/duplicate")
async def duplicate_strategy_endpoint(data: dict[str, Any]) -> Any:
    """Duplicate an existing strategy into a custom editable copy."""
    source_slug = str(data.get("source_slug") or "").strip()
    if not source_slug:
        return json_response({"error": "source_slug is required"}, 400)
    try:
        return await duplicate_strategy(source_slug, data.get("name"))
    except ValueError as exc:
        return json_response({"error": str(exc)}, 404)


@post(path="/strategies")
async def create_strategy_endpoint(data: dict[str, Any]) -> Any:
    """Create a blank custom strategy."""
    name = str(data.get("name") or "").strip()
    if not name:
        return json_response({"error": "name is required"}, 400)
    return await create_blank_strategy(name)


@post(path="/strategies/validate")
async def validate_strategy_endpoint(data: dict[str, Any]) -> Any:
    """Validate a draft Moonwalker strategy IR."""
    ir = data.get("ir")
    if not isinstance(ir, dict):
        return json_response({"error": "ir must be an object"}, 400)
    return validate_strategy_ir(ir)


@put(path="/strategies/{slug:str}")
async def save_strategy(slug: str, data: dict[str, Any]) -> Any:
    """Promote a validated custom strategy draft to a new active version."""
    ir = data.get("ir")
    if not isinstance(ir, dict):
        return json_response({"error": "ir must be an object"}, 400)
    try:
        base_lock_version = int(data.get("base_lock_version"))
    except (TypeError, ValueError):
        return json_response({"error": "base_lock_version is required"}, 400)

    try:
        payload, status_code = await promote_strategy_version(
            slug,
            ir,
            base_lock_version,
        )
    except PermissionError as exc:
        return json_response({"error": str(exc)}, 409)
    except ValueError as exc:
        return json_response({"error": str(exc)}, 404)

    if status_code != 200:
        return json_response(payload, status_code)
    return payload


@delete(path="/strategies/{slug:str}", status_code=200)
async def delete_strategy(slug: str) -> Any:
    """Delete a custom Strategy Builder definition."""
    try:
        await delete_custom_strategy(slug)
    except PermissionError as exc:
        return json_response({"error": str(exc)}, 409)
    except ValueError as exc:
        return json_response({"error": str(exc)}, 404)
    return {"deleted": True, "slug": slug}


route_handlers = [
    list_strategies,
    get_strategy,
    duplicate_strategy_endpoint,
    create_strategy_endpoint,
    validate_strategy_endpoint,
    save_strategy,
    delete_strategy,
]
