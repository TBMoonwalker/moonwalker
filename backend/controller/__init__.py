import mimetypes
from importlib import import_module
from pathlib import Path
from quart import Blueprint

controller = Blueprint(
    "controller",
    __name__,
    static_folder="../static",
    template_folder="../templates",
)

# Load controller modules
for mod in __loader__.get_resource_reader().contents():
    if "python" not in str(mimetypes.guess_type(mod)[0]):
        continue

    mod = Path(mod).stem
    if mod == "__init__":
        continue

    import_module(__package__ + "." + mod, __package__)
