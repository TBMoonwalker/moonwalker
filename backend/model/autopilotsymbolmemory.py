"""Persisted per-symbol Autopilot memory snapshots."""

from tortoise import fields
from tortoise.models import Model


class AutopilotSymbolMemory(Model):
    """Persist the latest trust snapshot for one symbol."""

    id = fields.IntField(primary_key=True)
    symbol = fields.CharField(max_length=50, unique=True)
    trust_score = fields.FloatField(default=50.0)
    trust_direction = fields.CharField(max_length=16, default="neutral")
    confidence_bucket = fields.CharField(max_length=16, default="warming_up")
    confidence_progress = fields.FloatField(default=0.0)
    sample_size = fields.IntField(default=0)
    profitable_closes = fields.IntField(default=0)
    loss_count = fields.IntField(default=0)
    slow_close_count = fields.IntField(default=0)
    weighted_profit_percent = fields.FloatField(default=0.0)
    weighted_close_hours = fields.FloatField(default=0.0)
    tp_delta_ratio = fields.FloatField(default=0.0)
    suggested_base_order = fields.FloatField(default=0.0)
    primary_reason_code = fields.CharField(max_length=64, null=True)
    primary_reason_value = fields.IntField(null=True)
    secondary_reason_code = fields.CharField(max_length=64, null=True)
    secondary_reason_value = fields.IntField(null=True)
    last_closed_at = fields.DatetimeField(null=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "autopilot_symbol_memory"
        indexes = (
            ("trust_direction", "trust_score"),
            ("updated_at",),
        )
