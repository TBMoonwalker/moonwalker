"""Autopilot memory event log model."""

from tortoise import fields
from tortoise.models import Model


class AutopilotMemoryEvent(Model):
    """Persist recent Autopilot memory events for cockpit read models."""

    id = fields.IntField(primary_key=True)
    event_type = fields.CharField(max_length=32)
    tone = fields.CharField(max_length=16, default="info")
    symbol = fields.CharField(max_length=50, null=True)
    reason_code = fields.CharField(max_length=64, null=True)
    reason_value = fields.IntField(null=True)
    trust_score = fields.FloatField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "autopilot_memory_events"
        indexes = (("created_at",), ("symbol", "created_at"))
