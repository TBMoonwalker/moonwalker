"""Strict transport-neutral operator commands for accumulation lifecycles."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.order_requests import normalize_order_symbol

if TYPE_CHECKING:
    from model import AccumulationLifecycleOperation

_OPERATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class AccumulationAction(StrEnum):
    """Explicit operator intent; a sell reason string is never authorization."""

    PAUSE = "pause"
    RESUME = "resume"
    CLOSE = "close"
    RETRY_CLOSE = "retry_close"
    ARCHIVE_DUST = "archive_dust"
    SELL_PARTIAL = "sell_partial"
    SWITCH_STRATEGY = "switch_strategy"
    REACTIVATE = "reactivate"


CLOSE_ACTIONS = frozenset({"close", "retry_close"})
SALE_ACTIONS = CLOSE_ACTIONS | {"sell_partial"}
# Entry validation belongs to an explicit entry request, never the runtime worker.
ENTRY_ACTIONS = frozenset({"activate", "correct_import", "retry_entry"})
RETIRABLE_ACTIONS = (
    ENTRY_ACTIONS | SALE_ACTIONS | {"pause", "resume", "reactivate", "switch_strategy"}
)


def validate_operation_id(value: Any) -> str:
    """Require a stable, bounded client operation identity."""
    if not isinstance(value, str) or not _OPERATION_ID.fullmatch(value):
        raise AccumulationStateError("A valid operation_id is required.")
    return value


@dataclass(frozen=True)
class AccumulationCommand:
    """Normalized command whose complete content is used for retry identity."""

    symbol: str
    action: AccumulationAction
    operation_id: str
    expected_revision: int
    target_version_id: int | None = None
    quantity: str | None = None
    previous_operation_id: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AccumulationCommand:
        """Reject ambiguous, unknown or missing fields before touching storage."""
        required = {"symbol", "action", "operation_id", "expected_revision"}
        if not isinstance(payload, dict) or not required <= payload.keys():
            raise AccumulationStateError("Missing accumulation command fields.")
        if not isinstance(payload["action"], str):
            raise AccumulationStateError("Invalid accumulation action.")
        try:
            action = AccumulationAction(payload["action"])
        except ValueError as exc:
            raise AccumulationStateError("Unsupported accumulation action.") from exc
        optional = (
            {"quantity"}
            if action == AccumulationAction.SELL_PARTIAL
            else {"previous_operation_id"}
            if action
            in {AccumulationAction.RETRY_CLOSE, AccumulationAction.ARCHIVE_DUST}
            else {"target_version_id"}
            if action == AccumulationAction.SWITCH_STRATEGY
            else set()
        )
        if set(payload) != required | optional:
            raise AccumulationStateError("Unexpected or missing command parameters.")
        revision = payload["expected_revision"]
        if type(revision) is not int or not 0 <= revision < 2**63 - 1:
            raise AccumulationStateError(
                "expected_revision must be a nonnegative integer."
            )
        target = payload.get("target_version_id")
        if action == AccumulationAction.SWITCH_STRATEGY and (
            type(target) is not int or not 0 < target < 2**63
        ):
            raise AccumulationStateError(
                "target_version_id must identify an exact version."
            )
        quantity = (
            canonical_decimal(payload["quantity"], positive=True)
            if action == AccumulationAction.SELL_PARTIAL
            else None
        )
        if not isinstance(payload["symbol"], str):
            raise AccumulationStateError("Invalid symbol.")
        return cls(
            normalize_order_symbol(payload["symbol"]),
            action,
            validate_operation_id(payload["operation_id"]),
            revision,
            target,
            quantity,
            validate_operation_id(payload["previous_operation_id"])
            if action
            in {AccumulationAction.RETRY_CLOSE, AccumulationAction.ARCHIVE_DUST}
            else None,
        )

    def request_json(self, account_scope: str) -> str:
        """Bind retries to the account and complete original command."""
        request = asdict(self)
        if self.previous_operation_id is None:
            # Preserve retry identity for commands persisted before close retries.
            request.pop("previous_operation_id")
        return json.dumps(
            {**request, "account_scope": account_scope},
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class AccumulationCommandResult:
    """Durable operation outcome, distinct from a current activation snapshot."""

    operation_id: str
    activation_id: str
    status: str
    state: str
    revision: int
    reason: str | None

    @classmethod
    def from_operation(
        cls, operation: AccumulationLifecycleOperation
    ) -> AccumulationCommandResult:
        """Read the persisted receipt without consulting current activation state."""
        return cls(
            operation.operation_id,
            str(operation.activation_id),
            operation.status,
            operation.result_state,
            operation.result_revision,
            operation.reason,
        )
