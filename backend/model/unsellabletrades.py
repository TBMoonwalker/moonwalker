"""Unsellable trade model."""

from tortoise import fields
from tortoise.models import Model


class UnsellableTrades(Model):
    """Persisted unsellable trade remnants removed from active bot management."""

    symbol = fields.CharField(max_length=50)
    so_count = fields.IntField(default=0)
    profit = fields.FloatField(default=0.0)
    profit_percent = fields.FloatField(default=0.0)
    amount = fields.FloatField(default=0.0)
    cost = fields.FloatField(default=0.0)
    current_price = fields.FloatField(default=0.0)
    avg_price = fields.FloatField(default=0.0)
    open_date = fields.TextField(null=True)
    unsellable_reason = fields.TextField(null=True)
    unsellable_min_notional = fields.FloatField(null=True)
    unsellable_estimated_notional = fields.FloatField(null=True)
    unsellable_since = fields.TextField(null=True)

    def __dict__(self):
        return (
            f"'symbol': {self.symbol}, 'so_count': {self.so_count}, "
            f"'profit': {self.profit}, 'profit_percent': {self.profit_percent}, "
            f"'amount': {self.amount}, 'cost': {self.cost}, "
            f"'current_price': {self.current_price}, 'avg_price': {self.avg_price}, "
            f"'open_date': {self.open_date}, "
            f"'unsellable_reason': {self.unsellable_reason}, "
            f"'unsellable_min_notional': {self.unsellable_min_notional}, "
            f"'unsellable_estimated_notional': {self.unsellable_estimated_notional}, "
            f"'unsellable_since': {self.unsellable_since}"
        )
