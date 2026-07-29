"""Explicit exchange guarantees required for crash-safe placement."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class UnsupportedExchangeCapability(ValueError):
    """Raised when live placement cannot be reconciled safely."""


class ExchangeSubmissionIndeterminate(Exception):
    """Raised when an exchange may have accepted a request but lost the response."""

    def __init__(
        self,
        *,
        action: str,
        symbol: str,
        client_order_id: str | None,
        operation_id: str | None = None,
    ) -> None:
        self.action = action
        self.symbol = symbol
        self.client_order_id = client_order_id
        self.operation_id = operation_id
        super().__init__(f"{action} for {symbol} has an indeterminate exchange outcome")


class ExchangePostSubmissionFailure(Exception):
    """Report accepted exchange evidence that still needs local reconciliation."""

    def __init__(
        self,
        *,
        action: str,
        symbol: str,
        order: dict[str, Any],
        cause: Exception | None = None,
        operation_id: str | None = None,
    ) -> None:
        self.action = action
        self.symbol = symbol
        self.order = dict(order)
        self.cause = cause
        self.operation_id = operation_id
        super().__init__(
            f"{action} for {symbol} was accepted but local finalization failed"
        )


class ExchangeOrderLookupStatus(StrEnum):
    """Typed distinction between absence and an unavailable exchange lookup."""

    FOUND = "found"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ExchangeOrderLookupResult:
    """Result of reconciling a durable identity against the exchange."""

    status: ExchangeOrderLookupStatus
    order: dict[str, Any] | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ExchangePlacementCapabilities:
    """Reconciliation guarantees for one configured CCXT exchange."""

    exchange_id: str
    client_order_id_parameter: str
    stable_client_order_id: bool
    lookup_by_client_order_id: bool
    lookup_by_exchange_order_id: bool
    order_history: bool
    deterministic_cancellation: bool
    supported_order_types: frozenset[str]

    @property
    def supports_safe_placement(self) -> bool:
        """Return whether unknown acceptance can be reconciled without retry."""
        return all(
            (
                self.stable_client_order_id,
                self.lookup_by_client_order_id,
                self.lookup_by_exchange_order_id,
                self.order_history,
                self.deterministic_cancellation,
            )
        )


BINANCE_SPOT_CAPABILITIES = ExchangePlacementCapabilities(
    exchange_id="binance",
    client_order_id_parameter="clientOrderId",
    stable_client_order_id=True,
    lookup_by_client_order_id=True,
    lookup_by_exchange_order_id=True,
    order_history=True,
    deterministic_cancellation=True,
    supported_order_types=frozenset({"market", "limit"}),
)

EXCHANGE_PLACEMENT_CAPABILITIES = {
    BINANCE_SPOT_CAPABILITIES.exchange_id: BINANCE_SPOT_CAPABILITIES,
}


def resolve_exchange_placement_capabilities(
    config: dict[str, Any],
) -> ExchangePlacementCapabilities | None:
    """Return explicit guarantees for the configured exchange and market."""
    exchange_id = str(config.get("exchange") or "").strip().lower()
    market = str(config.get("market") or "spot").strip().lower()
    if market != "spot":
        return None
    return EXCHANGE_PLACEMENT_CAPABILITIES.get(exchange_id)


def require_exchange_placement_capabilities(
    config: dict[str, Any],
    *,
    order_type: str,
) -> ExchangePlacementCapabilities | None:
    """Fail closed when a configured exchange lacks a required guarantee.

    An omitted exchange remains a no-client configuration and is handled by the
    existing exchange initialization path. Once an exchange is named, placement
    requires an explicit capability record.
    """
    exchange_id = str(config.get("exchange") or "").strip().lower()
    if not exchange_id:
        return None

    capabilities = resolve_exchange_placement_capabilities(config)
    normalized_order_type = str(order_type or "").strip().lower()
    if (
        capabilities is None
        or not capabilities.supports_safe_placement
        or normalized_order_type not in capabilities.supported_order_types
    ):
        raise UnsupportedExchangeCapability(
            "Exchange placement is disabled because "
            f"'{exchange_id}' does not have verified idempotency and "
            f"reconciliation support for {normalized_order_type or 'unknown'} "
            "spot orders."
        )
    return capabilities


def build_client_order_id(operation_id: str) -> str:
    """Return a stable Binance-compatible client order identifier."""
    digest = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()[:28]
    return f"mw-{digest}"


def build_client_order_params(
    client_order_id: Any,
    capabilities: ExchangePlacementCapabilities | None = None,
) -> dict[str, str]:
    """Return CCXT parameters for a stable placement identity."""
    normalized = str(client_order_id or "").strip()
    if not normalized:
        return {}
    parameter = (
        capabilities.client_order_id_parameter
        if capabilities is not None
        else "clientOrderId"
    )
    return {parameter: normalized}
