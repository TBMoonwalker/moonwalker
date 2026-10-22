"""Process-local input hints for the single lifespan-owned accumulation worker.

No prices, balances, credentials or execution evidence cross this boundary.
Publishers and the owner run on the application's event loop. A disconnected
owner is a no-op; the recovery heartbeat remains authoritative.
"""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


class AccumulationInputNotifications:
    """Keep one explicit subscriber, with owner-checked cleanup across lifespans."""

    def __init__(self) -> None:
        self._owner: object | None = None
        self._listener: Callable[[str | None], None] | None = None

    def attach(self, owner: object, listener: Callable[[str | None], None]) -> None:
        """Bind only the worker which owns this application lifespan."""
        if self._owner is not None and self._owner is not owner:
            raise RuntimeError("An accumulation input subscriber already exists.")
        self._owner, self._listener = owner, listener

    @property
    def connected(self) -> bool:
        """Avoid preparing wallet-change snapshots when the feature has no owner."""
        return self._listener is not None

    def detach(self, owner: object) -> None:
        """Do not let an older lifespan detach its successor."""
        if self._owner is owner:
            self._owner, self._listener = None, None

    def publish(self, symbol: str | None = None) -> None:
        """Hint that one quote, or shared wallet/funding inputs, changed."""
        if self._listener is not None:
            try:
                self._listener(symbol)
            except Exception:  # noqa: BLE001 - observers cannot fail committed accounting.
                logger.exception("Accumulation input notification failed")


accumulation_input_notifications = AccumulationInputNotifications()
