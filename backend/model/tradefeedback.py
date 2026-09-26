"""Durable Pathfinder delivery receipts, including rejected outcomes."""

from tortoise import fields
from tortoise.models import Model


class TradeFeedback(Model):
    """One immutable outcome per deal and its delivery state."""

    deal_id = fields.CharField(max_length=36, unique=True)
    endpoint = fields.TextField()
    payload_json = fields.TextField(null=True)
    status = fields.CharField(max_length=24, default="pending", db_index=True)
    attempts = fields.IntField(default=0)
    next_attempt_at = fields.FloatField(default=0)
    last_error = fields.TextField(null=True)

    class Meta:
        table = "tradefeedback"
