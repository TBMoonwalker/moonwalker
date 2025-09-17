from quart import send_from_directory, render_template
from controller import controller
from pathlib import Path


@controller.route("/", defaults={"path": ""})
@controller.route("/<path:path>")
async def serve_vue(path):
    static_file = Path(controller.static_folder) / path
    if path and static_file.exists():
        return await send_from_directory(controller.static_folder, path)
    return await render_template("index.html")
