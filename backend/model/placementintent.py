"""Durable exchange placement intent model."""

from tortoise import fields
from tortoise.models import Model


class PlacementIntent(Model):
    """Persist one exchange side-effect attempt across retries and restarts."""

    id = fields.IntField(primary_key=True)
    operation_id = fields.CharField(max_length=64, unique=True)
    source_operation_id = fields.CharField(max_length=64, null=True)
    client_order_id = fields.CharField(max_length=128, null=True, unique=True)
    exchange_order_id = fields.CharField(max_length=128, null=True)
    exchange_name = fields.CharField(max_length=64)
    symbol = fields.CharField(max_length=50)
    action = fields.CharField(max_length=32)
    side = fields.CharField(max_length=8)
    order_type = fields.CharField(max_length=32)
    state = fields.CharField(max_length=32)
    deal_id = fields.CharField(max_length=36, null=True)
    campaign_id = fields.CharField(max_length=36, null=True)
    requested_quote = fields.FloatField(default=0.0)
    requested_amount = fields.FloatField(default=0.0)
    maximum_price = fields.FloatField(null=True)
    reserved_quote = fields.FloatField(default=0.0)
    request_json = fields.TextField(default="{}")
    result_json = fields.TextField(null=True)
    reason_code = fields.CharField(max_length=64, null=True)
    error_message = fields.TextField(null=True)
    reconciliation_attempts = fields.IntField(default=0)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    submitted_at = fields.DatetimeField(null=True)
    completed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "placement_intents"
        indexes = (
            ("state", "symbol"),
            ("exchange_order_id",),
            ("deal_id",),
        )
