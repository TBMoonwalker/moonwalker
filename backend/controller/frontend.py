"""Frontend routing and static asset delivery."""

import asyncio
import json
import mimetypes
import re
from pathlib import Path

from controller import STATIC_DIR, TEMPLATE_DIR
from litestar.exceptions import NotFoundException
from litestar.handlers import get
from litestar.params import FromPath
from litestar.response import File, Response
from staging_check import missing_referenced_assets

_HASHED_ASSET_PATTERN = re.compile(r".+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$")
DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"


def _resolve_relative_file(root: Path, relative_path: str) -> Path | None:
    """Resolve a user path safely under a given root directory."""
    normalized_path = relative_path.lstrip("/\\")
    target = (root / normalized_path).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        return None
    return target


def _staging_warning_message(index_file: Path) -> str:
    """Build the actionable not-staged message for a missing entrypoint."""
    return f"Frontend not staged: {index_file} is missing. Run './run.sh start' to build and copy the Vue app into backend/templates and backend/static."


def _partial_staging_message(index_file: Path, missing: list[str]) -> str:
    """Build the actionable message for a partially staged frontend."""
    return f"Frontend partially staged: {index_file} references assets missing from {STATIC_DIR}: {', '.join(missing)}. Run './run.sh start' to build and copy the Vue app into backend/templates and backend/static."


def frontend_staging_warning() -> str | None:
    """Return an actionable message when the staged SPA is incomplete.

    The frontend is built by ``run.sh`` and copied into ``backend/static`` and
    ``backend/templates``. When that copy is missing or partial (the
    entrypoint references a bundle that never staged), the SPA cannot
    bootstrap; this makes the cause obvious at startup and in the response
    body instead of a bare "Internal Server Error" or a blank page.
    """
    index_file = TEMPLATE_DIR / "index.html"
    if not index_file.is_file():
        return _staging_warning_message(index_file)
    missing = missing_referenced_assets(index_file, STATIC_DIR)
    if missing:
        return _partial_staging_message(index_file, missing)
    return None


def _cache_control_for_file(path: Path) -> str:
    """Return cache-control policy tuned for SPA index and hashed assets."""
    resolved_path = path.resolve()
    index_path = (TEMPLATE_DIR / "index.html").resolve()
    if resolved_path == index_path:
        return "no-cache"

    static_root = STATIC_DIR.resolve()
    hashed_assets_root = (STATIC_DIR / "assets").resolve()
    if hashed_assets_root in resolved_path.parents and _HASHED_ASSET_PATTERN.fullmatch(
        resolved_path.name
    ):
        return "public, max-age=31536000, immutable"
    if static_root in resolved_path.parents:
        return "public, max-age=3600"

    return "no-cache"


def _file_response(path: Path) -> File:
    """Return an inline file response with best-effort media type."""
    media_type, _ = mimetypes.guess_type(str(path))
    return File(
        path=path,
        content_disposition_type="inline",
        media_type=media_type,
        headers={"Cache-Control": _cache_control_for_file(path)},
    )


@get(path="/static/{file_path:path}", include_in_schema=False)
async def serve_static(file_path: FromPath[str]) -> File:
    """Serve files from backend/static."""
    static_file = _resolve_relative_file(STATIC_DIR, file_path)
    if static_file is None or not await asyncio.to_thread(static_file.is_file):
        raise NotFoundException("Static file not found")
    return _file_response(static_file)


@get(path="/assets/{file_path:path}", include_in_schema=False)
async def serve_assets(file_path: FromPath[str]) -> File:
    """Serve hashed frontend bundles at the Vite-generated /assets path."""
    asset_file = _resolve_relative_file(STATIC_DIR / "assets", file_path)
    if asset_file is None or not await asyncio.to_thread(asset_file.is_file):
        raise NotFoundException("Asset file not found")
    return _file_response(asset_file)


@get(path="/docs/{file_path:path}", include_in_schema=False)
async def serve_docs(file_path: FromPath[str]) -> File:
    """Serve local operator documentation files."""
    docs_file = _resolve_relative_file(DOCS_DIR, file_path)
    if docs_file is None or not await asyncio.to_thread(docs_file.is_file):
        raise NotFoundException("Documentation file not found")
    return _file_response(docs_file)


@get(path="/{path:path}", include_in_schema=False)
async def serve_vue(path: FromPath[str]) -> File | Response:
    """Serve the Vue.js SPA entrypoint with static-file fallback."""
    return await _serve_vue_path(path)


@get(
    path=["/control-center", "/monitoring", "/config", "/settings"],
    include_in_schema=False,
)
async def serve_spa_top_level_routes() -> File | Response:
    """Serve top-level SPA routes that would otherwise collide with API prefixes.

    These are exact routes: without them Litestar's routing tree lets the
    matching API prefix (e.g. the config controller's ``/config/*`` handlers)
    claim the bare path and 404, so the browser never receives the SPA entry
    and the Vue router's redirect to /control-center never runs.
    """
    return await _serve_vue_path("")


async def _serve_vue_path(path: str) -> File | Response:
    """Serve a SPA route by path with static-file fallback."""
    candidate = None
    if path:
        candidate = _resolve_relative_file(STATIC_DIR, path)
    if candidate is not None and await asyncio.to_thread(candidate.is_file):
        return _file_response(candidate)

    index_file = TEMPLATE_DIR / "index.html"
    # Probe the full stage (entrypoint plus referenced assets) off the event
    # loop so the entrypoint read and the asset stats cannot stall the loop
    # shared with trading tasks; the message comes from the shared helper.
    staging_warning = await asyncio.to_thread(frontend_staging_warning)
    if staging_warning is not None:
        # Return a controlled body instead of raising: Litestar masks the
        # detail of 5xx HTTPExceptions into a generic error body, so a raise
        # would hide the actionable message from the browser.
        return Response(
            status_code=500,
            media_type="application/json",
            content=json.dumps({"detail": staging_warning}),
        )
    return _file_response(index_file)


@get(path="/", include_in_schema=False)
async def serve_root() -> File | Response:
    """Serve the Vue.js SPA entrypoint for the root path."""
    return await _serve_vue_path("")


route_handlers = [
    serve_static,
    serve_assets,
    serve_docs,
    serve_spa_top_level_routes,
    serve_vue,
    serve_root,
]
