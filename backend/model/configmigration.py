"""Configuration migration ledger model."""

from tortoise import fields
from tortoise.models import Model


class ConfigMigration(Model):
    """Record one idempotent configuration migration and its recovery snapshot."""

    id = fields.IntField(primary_key=True)
    version = fields.CharField(max_length=100, unique=True)
    backup_json = fields.TextField()
    applied_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "config_migrations"
