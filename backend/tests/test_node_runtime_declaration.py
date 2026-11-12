"""Regression tests for the pinned Node runtime declaration.

The Node floor is declared in three places that must stay in sync:
``.nvmrc`` (the exact pinned version), the ``engines`` field of
``frontend/package.json`` (the range npm enforces) and
``scripts/node_runtime.sh`` (the runtime guard used by CI and the
startup script). A bump that updates only one of them breaks
``nvm use``, ``npm install`` and CI in different orders, so this test
pins the three against each other.
"""

import json
import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
NVMRC = ROOT_DIR / ".nvmrc"
PACKAGE_JSON = ROOT_DIR / "frontend" / "package.json"
NODE_RUNTIME_GUARD = ROOT_DIR / "scripts" / "node_runtime.sh"


def _pinned_version() -> str:
    return NVMRC.read_text().strip()


def _engines() -> dict[str, str]:
    return json.loads(PACKAGE_JSON.read_text())["engines"]


def test_nvmrc_pins_a_full_semver() -> None:
    """The pin is a complete version so nvm installs one exact build."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", _pinned_version())


def test_nvmrc_pin_satisfies_the_package_json_node_range() -> None:
    """The exact pin must live inside the range npm enforces."""
    pinned = tuple(int(part) for part in _pinned_version().split("."))
    spec = _engines()["node"]
    floor_spec, ceiling_spec = spec.split()
    floor = tuple(int(part) for part in floor_spec.lstrip(">=").split("."))
    ceiling = int(ceiling_spec.lstrip("<"))

    assert floor <= pinned, f".nvmrc pins {_pinned_version()} below {spec!r}"
    assert pinned[0] < ceiling, f".nvmrc pins {_pinned_version()} at {spec!r}"


def test_node_runtime_guard_pins_the_same_majors() -> None:
    """CI and startup guard the same Node/npm majors the pin and range use."""
    node_major = _pinned_version().split(".")[0]
    npm_major = _engines()["npm"].split()[0].lstrip(">=").split(".")[0]
    guard = NODE_RUNTIME_GUARD.read_text()

    pinned_majors = re.findall(r"=~ \^(\d+)\\.", guard)
    assert pinned_majors == [node_major, npm_major], (
        "scripts/node_runtime.sh guards "
        f"{pinned_majors}, expected node {node_major} and npm {npm_major}"
    )
