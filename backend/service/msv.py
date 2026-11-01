"""Minimum-supported-version (MSV) preflight.

Phase 0 of the legacy-migration removal plan.  This module records a
non-self-healing baseline that distinguishes a *fresh* database, a *supported*
install, and a *pre-floor* install so that later removal phases can declare which
legacy code is safe to drop.  ``preflight_msv`` runs inside
``Database.init`` after the schema and ledger tables exist but *before* any
schema or config migration callback runs, so it reads the install's last-known
ledger state rather than a self-healing one.

Report only: preflight never blocks startup and never mutates the ledgers.
"""

from __future__ import annotations

from dataclasses import dataclass

from model import ConfigMigration, SchemaMigration

MINIMUM_SUPPORTED_VERSION = "4.9.0.0"

# The floor is the sidestep-removal release (b844b4c / 4.9.0.0).  That release
# deliberately added no schema migration, so the schema ledger is identical
# between a 4.8.x and a 4.9.x install and cannot tell them apart.  The durable,
# non-self-healing marker that an install has reached the floor is therefore the
# *configuration* migration row ``2026-09-sidestep-removal-v1`` in the
# ``config_migrations`` ledger: it is written once when that release first runs
# and is never removed, so its presence in the ledger outlives the install that
# wrote it.  The literal is owned here: the floor meaning belongs to msv, not
# to the (now removed) trade-mode migration module.
FLOOR_CONFIG_MIGRATION_ROW = "2026-09-sidestep-removal-v1"

# The config keys that only pre-floor (pre-4.9) databases carry.  Their
# presence marks pre-floor config residue: a database that still has them has
# not run the floor release and keeps reporting ``unsupported``; a clean
# database may be marked at the floor by ``config_migrations``.  Backup
# restore drops these keys silently (see ``backup_restore``).
LEGACY_TRADE_MODE_KEYS = frozenset(
    {
        "trade_lifecycle_mode",
        "dynamic_dca",
        "sidestep_campaign_enabled",
    }
)

UPGRADE_GUIDANCE = (
    "Upgrade through 4.9.0.0 (the sidestep-removal release) on the current code, "
    "then export a fresh backup before relying on any removed legacy bridge being "
    'absent. See docs/operations.md, "Minimum supported version".'
)


class MsvStatus:
    """Baseline outcomes, declared as constants instead of a dataclass field."""

    FRESH = "fresh"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class MsvBaseline:
    """One recorded pass of the MSV preflight over a database's ledger state."""

    minimum_supported_version: str
    floor_config_migration: str
    status: str
    floor_applied: bool
    schema_history_present: bool

    @property
    def supported(self) -> bool:
        """Whether the install is safe for post-floor removal (fresh or at floor)."""
        return self.status in (MsvStatus.FRESH, MsvStatus.SUPPORTED)

    @property
    def upgrade_guidance(self) -> str:
        """Operator action, or the empty string when no upgrade is required."""
        if self.supported:
            return ""
        return UPGRADE_GUIDANCE

    @property
    def summary(self) -> str:
        """One-line, log-safe description of the baseline."""
        supported = self.minimum_supported_version
        if self.status == MsvStatus.SUPPORTED:
            return (
                f"baseline at/after MSV {supported} "
                f"(config migration {self.floor_config_migration} present)"
            )
        if self.status == MsvStatus.FRESH:
            return "fresh database; no migration history yet (assumed supported)"
        return (
            f"baseline pre-MSV {supported}; "
            "schema history present but floor config migration "
            f"{self.floor_config_migration} not found"
        )


def evaluate_msv_baseline(
    floor_applied: bool,
    schema_history_present: bool,
) -> MsvBaseline:
    """Derive a baseline from pre-migration ledger state.

    A floor row proves the install last ran at or after the floor.  Its absence
    on a non-fresh database means the install pre-dates the floor.  A fresh
    database carries neither the floor row nor any schema history, so it is
    treated as supported and will receive every current migration.

    Args:
        floor_applied: Whether the floor config migration is in the ledger.
        schema_history_present: Whether any schema migration is recorded.

    Returns:
        A frozen :class:`MsvBaseline` describing the install.
    """
    if floor_applied:
        status = MsvStatus.SUPPORTED
    elif schema_history_present:
        status = MsvStatus.UNSUPPORTED
    else:
        status = MsvStatus.FRESH

    return MsvBaseline(
        minimum_supported_version=MINIMUM_SUPPORTED_VERSION,
        floor_config_migration=FLOOR_CONFIG_MIGRATION_ROW,
        status=status,
        floor_applied=floor_applied,
        schema_history_present=schema_history_present,
    )


_latest_baseline: MsvBaseline | None = None


async def preflight_msv() -> MsvBaseline:
    """Read the ledger pre-migrations and record the current MSV baseline."""
    floor_applied = await ConfigMigration.filter(
        version=FLOOR_CONFIG_MIGRATION_ROW
    ).exists()
    schema_history_present = await SchemaMigration.filter().exists()
    baseline = evaluate_msv_baseline(floor_applied, schema_history_present)
    set_msv_baseline(baseline)
    return baseline


def set_msv_baseline(baseline: MsvBaseline | None) -> None:
    """Store the most recent baseline for the reporting surface."""
    global _latest_baseline
    _latest_baseline = baseline


def get_msv_baseline() -> MsvBaseline | None:
    """Return the most recent baseline, or ``None`` before preflight runs."""
    return _latest_baseline
