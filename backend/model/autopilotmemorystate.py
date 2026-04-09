"""Persisted Autopilot memory service status."""

from tortoise import fields
from tortoise.models import Model


class AutopilotMemoryState(Model):
    """Persist the latest global Autopilot memory status."""

    id = fields.IntField(primary_key=True)
    status = fields.CharField(max_length=32, default="empty")
    enabled = fields.BooleanField(default=False)
    stale_reason = fields.CharField(max_length=64, null=True)
    baseline_mode_active = fields.BooleanField(default=True)
    current_closes = fields.IntField(default=0)
    required_closes = fields.IntField(default=20)
    symbols_considered = fields.IntField(default=0)
    trusted_symbols = fields.IntField(default=0)
    cooling_symbols = fields.IntField(default=0)
    featured_symbol = fields.CharField(max_length=50, null=True)
    featured_direction = fields.CharField(max_length=16, null=True)
    featured_reason_code = fields.CharField(max_length=64, null=True)
    featured_reason_value = fields.IntField(null=True)
    adaptive_tp_min = fields.FloatField(null=True)
    adaptive_tp_max = fields.FloatField(null=True)
    suggested_base_order_min = fields.FloatField(null=True)
    suggested_base_order_max = fields.FloatField(null=True)
    last_updated_at = fields.DatetimeField(null=True)
    last_success_at = fields.DatetimeField(null=True)

    class Meta:
        table = "autopilot_memory_state"
