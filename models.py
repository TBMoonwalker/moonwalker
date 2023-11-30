from tortoise import fields
from tortoise.models import Model


class Trades(Model):
    id = fields.IntField(pk=True)
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

    def __dict__(self):
        return f"'id': {self.id}, 'timestamp': {self.timestamp}, 'ordersize': {self.ordersize}, 'amount': {self.ordersize}, 'price': {self.price}, 'symbol': {self.symbol}, 'orderid': {self.orderid}, 'bot': {self.bot}, 'ordertype': {self.ordertype}, 'baseorder': {self.baseorder}, 'safetyorder': {self.safetyorder}, 'direction': {self.direction}, 'side': {self.side}"


class OpenTrades(Model):
    symbol = fields.CharField(max_length=50, unique=True)
    so_count = fields.IntField(null=True)
    profit = fields.FloatField(null=True)
    profit_percent = fields.FloatField(null=True)
    amount = fields.FloatField(null=True)
    cost = fields.FloatField(null=True)
    current_price = fields.FloatField(null=True)
    tp_price = fields.FloatField(null=True)
    avg_price = fields.FloatField(null=True)
    open_date = fields.TextField(null=True)

    def __dict__(self):
        return f"'symbol': {self.symbol}, 'so_count': {self.so_count}, 'profit': {self.profit}, 'profit_percent': {self.profit_percent}, 'amount': {self.amount}, 'cost': {self.cost}, 'tp_price': {self.tp_price}, 'avg_price': {self.avg_price}, 'open_date': {self.open_date}"


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
