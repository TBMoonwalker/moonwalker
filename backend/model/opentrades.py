"""Open trade model."""

from tortoise import fields
from tortoise.models import Model


class OpenTrades(Model):
    """Persisted open trade records."""

    symbol = fields.CharField(max_length=50, unique=True)
    so_count = fields.IntField(default=0)
    profit = fields.FloatField(default=0.0)
    profit_percent = fields.FloatField(default=0.0)
    amount = fields.FloatField(default=0.0)
    cost = fields.FloatField(default=0.0)
    current_price = fields.FloatField(default=0.0)
    tp_price = fields.FloatField(default=0.0)
    avg_price = fields.FloatField(default=0.0)
    open_date = fields.TextField(null=True)
    sold_amount = fields.FloatField(default=0.0)
    sold_proceeds = fields.FloatField(default=0.0)
    unsellable_amount = fields.FloatField(default=0.0)
    unsellable_reason = fields.TextField(null=True)
    unsellable_min_notional = fields.FloatField(null=True)
    unsellable_estimated_notional = fields.FloatField(null=True)
    unsellable_since = fields.TextField(null=True)
    unsellable_notice_sent = fields.BooleanField(default=False)

    def __dict__(self):
        return (
            f"'symbol': {self.symbol}, 'so_count': {self.so_count}, "
            f"'profit': {self.profit}, 'profit_percent': {self.profit_percent}, "
            f"'amount': {self.amount}, 'cost': {self.cost}, 'tp_price': {self.tp_price}, "
            f"'avg_price': {self.avg_price}, 'open_date': {self.open_date}, "
            f"'sold_amount': {self.sold_amount}, 'sold_proceeds': {self.sold_proceeds}, "
            f"'unsellable_amount': {self.unsellable_amount}, "
            f"'unsellable_reason': {self.unsellable_reason}, "
            f"'unsellable_min_notional': {self.unsellable_min_notional}, "
            f"'unsellable_estimated_notional': {self.unsellable_estimated_notional}, "
            f"'unsellable_since': {self.unsellable_since}, "
            f"'unsellable_notice_sent': {self.unsellable_notice_sent}"
        )
