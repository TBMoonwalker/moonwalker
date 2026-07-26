"""Persisted invalidation token for the AI trust analytics read model."""

from tortoise import fields
from tortoise.models import Model


class AiTrustAnalyticsRevision(Model):
    """Store the revision token used to invalidate reduced analytics payloads."""

    id = fields.IntField(primary_key=True)
    revision = fields.CharField(max_length=36)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "ai_trust_analytics_revision"
