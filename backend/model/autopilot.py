"""Autopilot mode history model."""

from tortoise import fields
from tortoise.models import Model


class Autopilot(Model):
    """Persisted autopilot mode snapshots."""

    id = fields.IntField(pk=True)
    mode = fields.CharField(max_length=10)

    class Meta:
        table = "autopilot"
