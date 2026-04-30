"""Open trade model."""

from tortoise import fields
from tortoise.models import Model


class OpenTrades(Model):
    """Persisted open trade records."""

    symbol = fields.CharField(max_length=50, unique=True)
    deal_id = fields.CharField(max_length=36, null=True, unique=True)
    campaign_id = fields.CharField(max_length=36, null=True)
    execution_history_complete = fields.BooleanField(default=True)
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
    tp_limit_order_id = fields.CharField(max_length=128, null=True)
    tp_limit_order_price = fields.FloatField(null=True)
    tp_limit_order_amount = fields.FloatField(null=True)
    tp_limit_order_armed_at = fields.TextField(null=True)

    def __dict__(self):
        return (
            f"'symbol': {self.symbol}, 'deal_id': {self.deal_id}, "
            f"'campaign_id': {self.campaign_id}, "
            f"'execution_history_complete': {self.execution_history_complete}, "
            f"'so_count': {self.so_count}, "
            f"'profit': {self.profit}, 'profit_percent': {self.profit_percent}, "
            f"'amount': {self.amount}, 'cost': {self.cost}, 'tp_price': {self.tp_price}, "
            f"'avg_price': {self.avg_price}, 'open_date': {self.open_date}, "
            f"'sold_amount': {self.sold_amount}, 'sold_proceeds': {self.sold_proceeds}, "
            f"'unsellable_amount': {self.unsellable_amount}, "
            f"'unsellable_reason': {self.unsellable_reason}, "
            f"'unsellable_min_notional': {self.unsellable_min_notional}, "
            f"'unsellable_estimated_notional': {self.unsellable_estimated_notional}, "
            f"'unsellable_since': {self.unsellable_since}, "
            f"'unsellable_notice_sent': {self.unsellable_notice_sent}, "
            f"'tp_limit_order_id': {self.tp_limit_order_id}, "
            f"'tp_limit_order_price': {self.tp_limit_order_price}, "
            f"'tp_limit_order_amount': {self.tp_limit_order_amount}, "
            f"'tp_limit_order_armed_at': {self.tp_limit_order_armed_at}"
        )
