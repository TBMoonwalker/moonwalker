"""ATH cache model."""

from tortoise import fields
from tortoise.models import Model


class AthCache(Model):
    """Persisted ATH values by symbol and window."""

    symbol = fields.CharField(max_length=50)
    window = fields.CharField(max_length=8)
    ath = fields.FloatField(default=0.0)
    source_timeframe = fields.CharField(max_length=8, default="1h")
    window_days = fields.IntField(default=7)
    updated_at = fields.DatetimeField(auto_now=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "ath_cache"
        unique_together = (("symbol", "window"),)
