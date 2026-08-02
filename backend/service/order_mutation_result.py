"""Typed result contract for operator-visible trade mutations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class OrderMutationStatus(StrEnum):
    """Stable outcomes understood by API clients."""

    APPLIED = "applied"
    DEDUPLICATED = "deduplicated"
    REJECTED = "rejected"
    STALE = "stale"
    INDETERMINATE = "indeterminate"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class OrderMutationResult:
    """Describe whether and how one lifecycle mutation took effect."""

    operation_id: str
    symbol: str
    action: str
    status: OrderMutationStatus
    reason_code: str
    user_message: str
    exchange_order_id: str | None = None
    client_order_id: str | None = None
    persisted_execution_id: str | None = None

    @property
    def applied(self) -> bool:
        """Return whether callers may treat the requested effect as complete."""
        return self.status in {
            OrderMutationStatus.APPLIED,
            OrderMutationStatus.DEDUPLICATED,
        }

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible API payload."""
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload
