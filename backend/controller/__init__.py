"""Controller route handler loader."""

import importlib.resources as resources
from importlib import import_module
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"

route_handlers: list[Any] = []


def _import_module_handlers(module_name: str, package: str) -> None:
    """Import module and register its declared Litestar route handlers."""
    module = import_module(f"{package}.{module_name}", package)
    handlers = getattr(module, "route_handlers", None)
    if isinstance(handlers, list):
        route_handlers.extend(handlers)


# Load controller modules and import frontend last so catch-all routes
# do not shadow API routes.
package = __package__
if package:
    modules: list[str] = []
    for mod in resources.files(package).iterdir():
        if mod.suffix != ".py":
            continue
        if mod.stem in {"__init__", "responses"}:
            continue
        modules.append(mod.stem)

    for module_name in sorted(name for name in modules if name != "frontend"):
        _import_module_handlers(module_name, package)
    if "frontend" in modules:
        _import_module_handlers("frontend", package)
