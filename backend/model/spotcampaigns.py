"""Spot sidestep campaign model."""

from tortoise import fields
from tortoise.models import Model


class SpotCampaigns(Model):
    """Persisted spot sidestep campaigns spanning multiple legs."""

    id = fields.IntField(primary_key=True)
    campaign_id = fields.CharField(max_length=36, unique=True)
    symbol = fields.CharField(max_length=50)
    state = fields.CharField(max_length=32)
    started_at = fields.TextField()
    last_transition_at = fields.TextField()
    current_deal_id = fields.CharField(max_length=36, null=True)
    sidestep_count = fields.IntField(default=0)
    last_exit_reason = fields.TextField(null=True)
    cooldown_until = fields.TextField(null=True)
    tp_percent = fields.FloatField(default=0.0)
    metadata_json = fields.TextField(null=True)

    class Meta:
        table = "spotcampaigns"
        indexes = (
            ("symbol",),
            ("state", "symbol"),
            ("current_deal_id",),
            ("last_transition_at",),
        )
