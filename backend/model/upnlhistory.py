"""uPNL history model."""

from tortoise import fields
from tortoise.models import Model


class UpnlHistory(Model):
    """Persisted uPNL snapshots for charting."""

    id = fields.IntField(primary_key=True)
    timestamp = fields.DatetimeField()
    upnl = fields.FloatField(default=0.0)
    profit_overall = fields.FloatField(default=0.0)

    class Meta:
        table = "upnl_history"
