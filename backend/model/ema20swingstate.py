"""EMA20 swing strategy state model."""

from tortoise import fields
from tortoise.models import Model


class Ema20SwingState(Model):
    """Persisted EMA20 swing state keyed by symbol and timeframe."""

    symbol = fields.CharField(max_length=50)
    timeframe = fields.CharField(max_length=12)
    previous_swing_low = fields.FloatField()
    previous_ema20 = fields.FloatField()
    updated_at = fields.DatetimeField(auto_now=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "ema20_swing_state"
        unique_together = (("symbol", "timeframe"),)
