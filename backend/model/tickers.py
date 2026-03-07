"""Ticker OHLCV model."""

from tortoise import fields
from tortoise.models import Model


class Tickers(Model):
    """Persisted OHLCV ticker records."""

    timestamp = fields.TextField()
    symbol = fields.TextField()
    open = fields.FloatField()
    high = fields.FloatField()
    low = fields.FloatField()
    close = fields.FloatField()
    volume = fields.FloatField()

    class Meta:
        table = "tickers"
        indexes = (
            ("symbol", "timestamp"),
            ("timestamp",),
        )

    def __dict__(self):
        return f"'id': {self.id}, 'timestamp': {self.timestamp}, 'symbol': {self.symbol}, 'open': {self.open}, 'high': {self.high},  'close': {self.close},  'volume': {self.volume}"
