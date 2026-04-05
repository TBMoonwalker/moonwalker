"""Archived OHLCV candles for closed-trade replay."""

from tortoise import fields
from tortoise.models import Model


class TradeReplayCandles(Model):
    """Persisted raw candles for one closed deal replay window."""

    id = fields.IntField(primary_key=True)
    deal_id = fields.CharField(max_length=36)
    symbol = fields.CharField(max_length=50)
    timestamp = fields.TextField()
    open = fields.FloatField()
    high = fields.FloatField()
    low = fields.FloatField()
    close = fields.FloatField()
    volume = fields.FloatField()

    class Meta:
        table = "tradereplaycandles"
        indexes = (
            ("deal_id", "timestamp"),
            ("symbol", "timestamp"),
        )
