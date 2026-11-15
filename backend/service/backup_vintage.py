"""Shared vocabulary for classifying backup payloads against the current schema.

The backup restore, the pre-confirmation classification preview, and the
startup campaign-residue gate all reason about the same legacy residue. This
module owns those definitions so the call sites cannot drift apart. See
docs/operations.md, "Backup And Restore".
"""

from __future__ import annotations

from typing import Any

# The seven sidestep-era waiting-state columns that the first contract
# migration (021) dropped from open trades. Pre-floor backups may still carry
# them; restore discards them silently because no live code writes or reads
# them. The refusal gate covers campaign references only: the hardening that
# would have extended it to this set was dropped 2026-11-08 with the 4.8.x
# compatibility (see TODOS.md).
SIDESTEP_WAITING_STATE_COLUMNS: frozenset[str] = frozenset(
    {
        "reserved_reentry_quote",
        "waiting_reference_price",
        "waiting_reference_amount",
        "waiting_reference_quote",
        "virtual_waiting_profit",
        "virtual_waiting_profit_percent",
        "last_transition_at",
    }
)


def campaign_residue_rows(
    open_trade_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the open-trade rows that still reference a legacy campaign.

    Args:
        open_trade_rows: Open-trade rows, whether from a backup payload or a
            database read.

    Returns:
        The rows whose ``campaign_id`` value is not null.
    """
    return [row for row in open_trade_rows if row.get("campaign_id") is not None]


def campaign_residue_symbols(residue_rows: list[dict[str, Any]]) -> list[str]:
    """Return the sorted, de-duplicated display symbols of residue rows.

    Args:
        residue_rows: Rows returned by :func:`campaign_residue_rows`.

    Returns:
        One symbol label per affected open trade, sorted for stable messages.
    """
    return sorted({str(row.get("symbol") or "<unknown>") for row in residue_rows})
