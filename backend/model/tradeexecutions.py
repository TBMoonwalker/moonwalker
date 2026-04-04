"""Trade execution ledger model."""

from tortoise import fields
from tortoise.models import Model


class TradeExecutions(Model):
    """Append-only execution rows for replay markers and analytics."""

    id = fields.IntField(primary_key=True)
    deal_id = fields.CharField(max_length=36)
    symbol = fields.CharField(max_length=50)
    side = fields.CharField(max_length=8)
    role = fields.CharField(max_length=32)
    timestamp = fields.TextField()
    price = fields.FloatField()
    amount = fields.FloatField()
    ordersize = fields.FloatField(default=0.0)
    fee = fields.FloatField(default=0.0)
    order_id = fields.TextField(null=True)
    order_type = fields.TextField(null=True)
    order_count = fields.IntField(null=True)
    so_percentage = fields.FloatField(null=True)
    signal_name = fields.TextField(null=True)
    strategy_name = fields.TextField(null=True)
    timeframe = fields.TextField(null=True)
    metadata_json = fields.TextField(null=True)

    class Meta:
        table = "tradeexecutions"
        indexes = (
            ("deal_id", "timestamp"),
            ("symbol", "timestamp"),
            ("side", "role"),
        )
