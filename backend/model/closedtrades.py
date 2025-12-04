from tortoise import fields
from tortoise.models import Model


class ClosedTrades(Model):
    symbol = fields.CharField(max_length=50)
    so_count = fields.IntField(null=True)
    profit = fields.FloatField(null=True)
    profit_percent = fields.FloatField(null=True)
    amount = fields.FloatField(null=True)
    cost = fields.FloatField(null=True)
    tp_price = fields.FloatField(null=True)
    avg_price = fields.FloatField(null=True)
    open_date = fields.TextField(null=True)
    close_date = fields.TextField(null=True)
    duration = fields.TextField(null=True)

    def __dict__(self):
        return f"'symbol': {self.symbol}, 'so_count': {self.so_count}, 'profit': {self.profit}, 'profit_percent': {self.profit_percent}, 'amount': {self.amount}, 'cost': {self.cost}, 'tp_price': {self.tp_price}, 'avg_price': {self.avg_price}, 'open_date': {self.open_date}, 'close_date': {self.close_date} 'close_date': {self.duration}"
