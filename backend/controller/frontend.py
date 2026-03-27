"""Frontend routing and static asset delivery."""

import asyncio
import mimetypes
import re
from pathlib import Path

from controller import STATIC_DIR, TEMPLATE_DIR
from litestar.exceptions import NotFoundException
from litestar.handlers import get
from litestar.response import File

_HASHED_ASSET_PATTERN = re.compile(r".+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$")


def _resolve_relative_file(root: Path, relative_path: str) -> Path | None:
    """Resolve a user path safely under a given root directory."""
    normalized_path = relative_path.lstrip("/\\")
    target = (root / normalized_path).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        return None
    return target


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
async def serve_static(file_path: str) -> File:
    """Serve files from backend/static."""
    static_file = _resolve_relative_file(STATIC_DIR, file_path)
    if static_file is None or not await asyncio.to_thread(static_file.is_file):
        raise NotFoundException("Static file not found")
    return _file_response(static_file)


@get(path="/assets/{file_path:path}", include_in_schema=False)
async def serve_assets(file_path: str) -> File:
    """Serve hashed frontend bundles at the Vite-generated /assets path."""
    asset_file = _resolve_relative_file(STATIC_DIR / "assets", file_path)
    if asset_file is None or not await asyncio.to_thread(asset_file.is_file):
        raise NotFoundException("Asset file not found")
    return _file_response(asset_file)


@get(path="/{path:path}", include_in_schema=False)
async def serve_vue(path: str) -> File:
    """Serve the Vue.js SPA entrypoint with static-file fallback."""
    return await _serve_vue_path(path)


@get(
    path=["/control-center", "/monitoring", "/config", "/settings"],
    include_in_schema=False,
)
async def serve_spa_top_level_routes() -> File:
    """Serve top-level SPA routes that would otherwise collide with API prefixes."""
    return await _serve_vue_path("")


async def _serve_vue_path(path: str) -> File:
    """Serve a SPA route by path with static-file fallback."""
    candidate = None
    if path:
        candidate = _resolve_relative_file(STATIC_DIR, path)
    if candidate is not None and await asyncio.to_thread(candidate.is_file):
        return _file_response(candidate)

    index_file = TEMPLATE_DIR / "index.html"
    return _file_response(index_file)


@get(path="/", include_in_schema=False)
async def serve_root() -> File:
    """Serve the Vue.js SPA entrypoint for the root path."""
    return await _serve_vue_path("")


route_handlers = [
    serve_static,
    serve_assets,
    serve_spa_top_level_routes,
    serve_vue,
    serve_root,
]
