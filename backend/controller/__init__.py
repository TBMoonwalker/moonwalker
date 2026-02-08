"""Controller blueprint and dynamic module loader."""

import importlib.resources as resources
from importlib import import_module

from quart import Blueprint

controller = Blueprint(
    "controller",
    __name__,
    static_folder="../static",
    template_folder="../templates",
)

# Load controller modules
package = __package__
if package:
    for mod in resources.files(package).iterdir():
        if mod.suffix != ".py":
            continue
        if mod.stem == "__init__":
            continue
        import_module(f"{package}.{mod.stem}", package)
