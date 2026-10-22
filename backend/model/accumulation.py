"""Durable accumulation identities, observations and opportunity history.

These records are independent of OpenTrades: an activation can exist before
the first purchase and must survive deletion of a fully closed holding.
"""

from uuid import uuid4

from tortoise import fields
from tortoise.models import Model


class AccumulationActivation(Model):
    """Retain a symbol's lifecycle and immutable strategy binding across closes."""

    id = fields.UUIDField(primary_key=True, default=uuid4)
    symbol = fields.CharField(max_length=50, unique=True)
    # An opaque operator/account identity, never an API key or credential.
    account_scope = fields.CharField(max_length=128)
    generation = fields.UUIDField(default=uuid4)
    state = fields.CharField(max_length=32, default="validating")
    explicitly_paused = fields.BooleanField(default=True)
    reason = fields.CharField(max_length=128, null=True)
    strategy_version = fields.ForeignKeyField(
        "models.StrategyVersion",
        related_name="accumulation_activations",
        on_delete=fields.RESTRICT,
        null=True,
    )
    holding = fields.OneToOneField(
        "models.OpenTrades",
        related_name="accumulation_activation",
        on_delete=fields.SET_NULL,
        null=True,
    )
    observation_epoch = fields.IntField(default=0)
    baseline_close_ms = fields.BigIntField(null=True)
    observations_initialized = fields.BooleanField(default=False)
    revision = fields.BigIntField(default=0)
    consumption_revision = fields.BigIntField(default=0)
    execution_guard_json = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "accumulation_activations"
        indexes = (("state", "symbol"),)


class AccumulationStrategyState(Model):
    """Store bounded observations separately from durable execution consumption."""

    id = fields.IntField(primary_key=True)
    activation = fields.ForeignKeyField(
        "models.AccumulationActivation",
        related_name="observations",
        on_delete=fields.RESTRICT,
    )
    strategy_version = fields.ForeignKeyField(
        "models.StrategyVersion",
        related_name="accumulation_observations",
        on_delete=fields.RESTRICT,
    )
    observation_epoch = fields.IntField()
    schema_version = fields.IntField(default=1)
    value_json = fields.TextField()
    last_processed_close_ms = fields.BigIntField()
    revision = fields.BigIntField(default=0)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "accumulation_strategy_states"
        unique_together = (("activation", "strategy_version", "observation_epoch"),)


class AccumulationOpportunity(Model):
    """Freeze a market event's identity independently of its placement attempts."""

    id = fields.UUIDField(primary_key=True, default=uuid4)
    activation = fields.ForeignKeyField(
        "models.AccumulationActivation",
        related_name="opportunities",
        on_delete=fields.RESTRICT,
    )
    generation = fields.UUIDField()
    strategy_version = fields.ForeignKeyField(
        "models.StrategyVersion",
        related_name="accumulation_opportunities",
        on_delete=fields.RESTRICT,
    )
    observation_epoch = fields.IntField()
    is_initial_entry = fields.BooleanField(default=False)
    signal_close_ms = fields.BigIntField()
    expires_at_ms = fields.BigIntField()
    signal_price = fields.TextField()
    signal_atr = fields.TextField()
    signal_peak = fields.TextField(null=True)
    status = fields.CharField(max_length=32, default="candidate")
    # Set to activation.id while unresolved, NULL only after reconciliation.
    # SQLite permits many NULLs but only one occupied slot per activation.
    unresolved_slot = fields.UUIDField(null=True, unique=True)
    consumed_at = fields.DatetimeField(null=True)
    consumption_revision = fields.BigIntField(null=True)
    retry_index = fields.IntField(default=0)
    next_retry_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "accumulation_opportunities"
        unique_together = (("activation", "observation_epoch", "signal_close_ms"),)
        indexes = (
            ("activation", "status", "signal_close_ms"),
            ("activation", "consumption_revision"),
        )


class AccumulationAttempt(Model):
    """Link existing execution intents to one opportunity without a new queue."""

    id = fields.IntField(primary_key=True)
    opportunity = fields.ForeignKeyField(
        "models.AccumulationOpportunity",
        related_name="attempts",
        on_delete=fields.RESTRICT,
    )
    placement = fields.OneToOneField(
        "models.PlacementIntent",
        related_name="accumulation_attempt",
        on_delete=fields.RESTRICT,
    )
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "accumulation_attempts"


class AccumulationLifecycleOperation(Model):
    """Persist an operator command and its outcome before any exchange effect."""

    id = fields.IntField(primary_key=True)
    operation_id = fields.CharField(max_length=64, unique=True)
    activation = fields.ForeignKeyField(
        "models.AccumulationActivation",
        related_name="lifecycle_operations",
        on_delete=fields.RESTRICT,
    )
    action = fields.CharField(max_length=32)
    request_json = fields.TextField()
    status = fields.CharField(max_length=24, default="pending")
    previous_state = fields.CharField(max_length=32)
    previous_paused = fields.BooleanField()
    result_state = fields.CharField(max_length=32)
    result_revision = fields.BigIntField()
    reason = fields.CharField(max_length=128, null=True)
    target_version = fields.ForeignKeyField(
        "models.StrategyVersion",
        related_name="accumulation_lifecycle_operations",
        on_delete=fields.RESTRICT,
        null=True,
    )
    requested_quantity = fields.TextField(null=True)
    placement = fields.OneToOneField(
        "models.PlacementIntent",
        related_name="accumulation_lifecycle_operation",
        on_delete=fields.RESTRICT,
        null=True,
    )
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "accumulation_lifecycle_operations"
        indexes = (("activation", "status"),)


class AccumulationFillCheckpoint(Model):
    """Deduplicate cumulative exchange evidence inside the inventory transaction."""

    id = fields.IntField(primary_key=True)
    placement = fields.OneToOneField(
        "models.PlacementIntent",
        related_name="accumulation_checkpoint",
        on_delete=fields.RESTRICT,
    )
    activation = fields.ForeignKeyField(
        "models.AccumulationActivation",
        related_name="fill_checkpoints",
        on_delete=fields.RESTRICT,
    )
    deal_id = fields.CharField(max_length=36, null=True)
    filled = fields.TextField(default="0")
    quote_cost = fields.TextField(default="0")
    fees_json = fields.TextField(default="{}")
    fees_complete = fields.BooleanField(default=False)
    terminal = fields.BooleanField(default=False)
    evidence_json = fields.TextField()
    inventory_json = fields.TextField(null=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "accumulation_fill_checkpoints"


class AccumulationReturnTotals(Model):
    """Derived lifetime returns, updated atomically with the immutable fill ledger."""

    id = fields.IntField(primary_key=True)
    activation = fields.OneToOneField(
        "models.AccumulationActivation",
        related_name="return_totals",
        on_delete=fields.CASCADE,
    )
    realized_quote = fields.TextField(default="0")
    last_quantity = fields.TextField(default="0", null=True)
    last_cost = fields.TextField(default="0", null=True)
    provenance_complete = fields.BooleanField(default=True)
    history_complete = fields.BooleanField(default=True)

    class Meta:
        table = "accumulation_return_totals"


class AccumulationReturnDay(Model):
    """Derived UTC daily returns; backup restore rebuilds these from execution deltas."""

    id = fields.IntField(primary_key=True)
    activation = fields.ForeignKeyField(
        "models.AccumulationActivation",
        related_name="return_days",
        on_delete=fields.CASCADE,
    )
    date = fields.CharField(max_length=10)
    profit = fields.TextField(default="0")

    class Meta:
        table = "accumulation_return_days"
        unique_together = (("activation", "date"),)
        indexes = (("date",),)
