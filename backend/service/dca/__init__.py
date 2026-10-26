"""Dynamic DCA services with the public engine export kept lazy.

Importing calculation or exchange adapters must not construct the trading engine
or pull Orders into their dependency graph.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from service.dca.engine import Dca as Dca

__all__ = ["Dca"]


def __getattr__(name: str) -> object:
    """Load the public engine only when its class is requested."""
    if name == "Dca":
        from service.dca.engine import Dca

        return Dca
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
