"""Ordered application schema and data migration ledger."""

from tortoise import fields
from tortoise.models import Model


class SchemaMigration(Model):
    """Record one resumable application migration and its compatibility contract."""

    id = fields.IntField(primary_key=True)
    version = fields.CharField(max_length=100, unique=True)
    phase = fields.CharField(max_length=32)
    description = fields.TextField()
    checksum = fields.CharField(max_length=64)
    compatibility = fields.CharField(max_length=100)
    status = fields.CharField(max_length=20)
    error = fields.TextField(null=True)
    started_at = fields.DatetimeField(null=True)
    applied_at = fields.DatetimeField(null=True)

    class Meta:
        table = "schema_migrations"
