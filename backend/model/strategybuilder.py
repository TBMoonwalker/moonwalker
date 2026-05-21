"""Strategy Builder persistence models."""

from tortoise import fields
from tortoise.models import Model


class StrategyDefinition(Model):
    """Editable strategy identity with immutable active versions."""

    slug = fields.CharField(max_length=96, unique=True)
    name = fields.CharField(max_length=120)
    description = fields.TextField(null=True)
    is_builtin = fields.BooleanField(default=False)
    duplicated_from = fields.CharField(max_length=96, null=True)
    active_version = fields.IntField(null=True)
    draft_version = fields.IntField(default=0)
    lock_version = fields.IntField(default=1)
    validation_status = fields.CharField(max_length=24, default="valid")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "strategy_definitions"


class StrategyVersion(Model):
    """Immutable Moonwalker strategy IR version."""

    strategy_slug = fields.CharField(max_length=96)
    version = fields.IntField()
    ir_json = fields.TextField()
    validation_json = fields.TextField()
    explanation = fields.TextField()
    created_at = fields.DatetimeField(auto_now_add=True)
    activated_at = fields.DatetimeField(null=True)

    class Meta:
        table = "strategy_versions"
        unique_together = (("strategy_slug", "version"),)


class StrategyGraphState(Model):
    """Typed graph state keyed by strategy, symbol, timeframe, and state key."""

    strategy_slug = fields.CharField(max_length=96)
    state_key = fields.CharField(max_length=96)
    symbol = fields.CharField(max_length=50)
    timeframe = fields.CharField(max_length=24)
    value_json = fields.TextField()
    updated_at = fields.DatetimeField(auto_now=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "strategy_graph_state"
        unique_together = (("strategy_slug", "state_key", "symbol", "timeframe"),)
