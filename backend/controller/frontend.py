"""Frontend routing and static asset delivery."""

from pathlib import Path
from typing import Any

from controller import controller
from quart import render_template, send_from_directory


@controller.route("/", defaults={"path": ""})
@controller.route("/<path:path>")
async def serve_vue(path: str) -> Any:
    """Serve the Vue.js frontend application.

    Args:
        path: Requested path. If it exists as a static file, serve it.
              Otherwise, serve the index.html for SPA routing.

    Returns:
        Static file if path exists, otherwise the index.html template.
    """
    static_file = Path(controller.static_folder) / path
    if path and static_file.exists():
        return await send_from_directory(controller.static_folder, path)
    return await render_template("index.html")
