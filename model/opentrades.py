from tortoise import fields
from tortoise.models import Model


class OpenTrades(Model):
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

    def __dict__(self):
        return f"'symbol': {self.symbol}, 'so_count': {self.so_count}, 'profit': {self.profit}, 'profit_percent': {self.profit_percent}, 'amount': {self.amount}, 'cost': {self.cost}, 'tp_price': {self.tp_price}, 'avg_price': {self.avg_price}, 'open_date': {self.open_date}"
