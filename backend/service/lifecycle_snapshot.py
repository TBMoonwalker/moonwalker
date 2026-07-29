"""Immutable identity for decisions that mutate a trade lifecycle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from service.order_requests import normalize_order_symbol


def _stable_revision(value: Any) -> str:
    """Return an opaque deterministic revision for JSON-compatible state."""
    serialized = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_config_revision(config: dict[str, Any]) -> str:
    """Return an opaque revision for one immutable runtime config snapshot."""
    return _stable_revision(config)


@dataclass(frozen=True)
class LifecycleSnapshotIdentity:
    """State that must still match before an evaluated action may execute."""

    symbol: str
    deal_id: str | None
    campaign_id: str | None
    execution_count: int
    config_revision: str
    automation_paused: bool
    exposure_state: str | None
    tp_limit_order_id: str | None
    dca_policy_revision: str

    @classmethod
    def from_trade(
        cls,
        trade: dict[str, Any],
        config: dict[str, Any],
    ) -> "LifecycleSnapshotIdentity":
        """Capture lifecycle identity from an aggregated trade and config."""
        policy_state = {
            "mode": trade.get("dca_sizing_mode"),
            "policy": trade.get("dca_policy_json"),
            "reference_price": trade.get("dca_reference_price"),
            "reference_atr_percent": trade.get("dca_reference_atr_percent"),
            "next_trigger_price": trade.get("dca_next_trigger_price"),
        }
        execution_count = int(
            trade.get("execution_count")
            or (1 + int(trade.get("safetyorders_count") or 0))
        )
        return cls(
            symbol=normalize_order_symbol(str(trade.get("symbol") or "")),
            deal_id=_optional_string(trade.get("deal_id")),
            campaign_id=_optional_string(trade.get("campaign_id")),
            execution_count=execution_count,
            config_revision=build_config_revision(config),
            automation_paused=bool(trade.get("automation_paused", False)),
            exposure_state=_optional_string(trade.get("exposure_state")),
            tp_limit_order_id=_optional_string(trade.get("tp_limit_order_id")),
            dca_policy_revision=_stable_revision(policy_state),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation for request boundaries."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LifecycleSnapshotIdentity":
        """Restore a normalized identity received at a service boundary."""
        return cls(
            symbol=normalize_order_symbol(str(payload.get("symbol") or "")),
            deal_id=_optional_string(payload.get("deal_id")),
            campaign_id=_optional_string(payload.get("campaign_id")),
            execution_count=int(payload.get("execution_count") or 0),
            config_revision=str(payload.get("config_revision") or ""),
            automation_paused=bool(payload.get("automation_paused", False)),
            exposure_state=_optional_string(payload.get("exposure_state")),
            tp_limit_order_id=_optional_string(payload.get("tp_limit_order_id")),
            dca_policy_revision=str(payload.get("dca_policy_revision") or ""),
        )


def _optional_string(value: Any) -> str | None:
    """Normalize an optional identity component."""
    normalized = str(value or "").strip()
    return normalized or None


def snapshots_match(
    expected: LifecycleSnapshotIdentity,
    current_trade: dict[str, Any] | None,
    config: dict[str, Any],
) -> bool:
    """Return whether a locked reload still matches the evaluated identity."""
    if current_trade is None:
        return False
    return expected == LifecycleSnapshotIdentity.from_trade(current_trade, config)
