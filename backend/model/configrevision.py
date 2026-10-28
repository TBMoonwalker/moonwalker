"""Durable generation for concurrent configuration editors."""

from tortoise import fields
from tortoise.models import Model


class ConfigRevision(Model):
    """One monotonically increasing generation for configuration writes."""

    id = fields.IntField(primary_key=True)
    revision = fields.BigIntField(default=0)

    class Meta:
        table = "config_revision"
