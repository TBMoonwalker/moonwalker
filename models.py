from tortoise import fields
from tortoise.models import Model


class Trades(Model):
    id = fields.IntField(pk=True)
    timestamp = fields.TextField()
    ordersize = fields.IntField()
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

    def __dict__(self):
        return f"'id': {self.id}, 'timestamp': {self.timestamp}, 'ordersize': {self.ordersize}, 'amount': {self.ordersize}, 'price': {self.price}, 'symbol': {self.symbol}, 'orderid': {self.orderid}, 'bot': {self.bot}, 'ordertype': {self.ordertype}, 'baseorder': {self.baseorder}, 'safetyorder': {self.safetyorder}, 'direction': {self.direction}, 'side': {self.side}"


class Statistics(Model):
    id = fields.IntField(pk=True)
    symbol = fields.TextField()
    so_count = fields.IntField()
    profit = fields.FloatField()
    profit_percent = fields.FloatField()
    amount = fields.FloatField()
    cost = fields.FloatField()
    duration = fields.DateField()

    def __dict__(self):
        return f"id': {self.id}, 'symbol': {self.symbol}, 'so_count': {self.so_count}, 'profit': {self.profit}, 'profit_percent': {self.profit_percent}, 'amount': {self.amount}, 'cost': {self.cost}, 'duration': {self.duration},"
