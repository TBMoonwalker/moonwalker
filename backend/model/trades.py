"""Trade model."""

from tortoise import fields
from tortoise.models import Model


class Trades(Model):
    """Persisted trade records."""

    id = fields.IntField(primary_key=True)
    timestamp = fields.TextField()
    ordersize = fields.FloatField()
    fee = fields.FloatField()
    precision = fields.IntField(null=True)
    amount = fields.FloatField()
    amount_fee = fields.FloatField()
    price = fields.FloatField()
    symbol = fields.TextField()
    orderid = fields.TextField()
    bot = fields.TextField()
    ordertype = fields.TextField()
    baseorder = fields.BooleanField(null=True)
    safetyorder = fields.BooleanField(null=True)
    order_count = fields.IntField(null=True)
    so_percentage = fields.DecimalField(max_digits=2, decimal_places=1, null=True)
    direction = fields.TextField()
    side = fields.TextField()

    class Meta:
        table = "trades"
        indexes = (
            ("symbol",),
            ("symbol", "baseorder"),
            ("symbol", "safetyorder", "baseorder"),
        )

    def __dict__(self):
        return f"'id': {self.id}, 'timestamp': {self.timestamp}, 'ordersize': {self.ordersize}, 'amount': {self.ordersize}, 'price': {self.price}, 'symbol': {self.symbol}, 'orderid': {self.orderid}, 'bot': {self.bot}, 'ordertype': {self.ordertype}, 'baseorder': {self.baseorder}, 'safetyorder': {self.safetyorder}, 'direction': {self.direction}, 'side': {self.side}"
