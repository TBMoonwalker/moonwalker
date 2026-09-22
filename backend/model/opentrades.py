"""Open trade model."""

from service.spot_campaign_types import TradeExposureState, TradeLifecycleMode
from tortoise import fields
from tortoise.models import Model


class OpenTrades(Model):
    """Persisted open trade records."""

    symbol = fields.CharField(max_length=50, unique=True)
    deal_id = fields.CharField(max_length=36, null=True, unique=True)
    campaign_id = fields.CharField(max_length=36, null=True)
    lifecycle_mode = fields.CharField(
        max_length=32,
        default=TradeLifecycleMode.CLASSIC_DCA.value,
    )
    exposure_state = fields.CharField(
        max_length=32,
        default=TradeExposureState.LONG_EXPOSED.value,
    )
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
    dca_sizing_mode = fields.CharField(max_length=32, default="legacy_factors")
    dca_policy_json = fields.TextField(null=True)
    dca_reference_price = fields.FloatField(default=0.0)
    dca_reference_atr_percent = fields.FloatField(default=0.0)
    dca_next_trigger_price = fields.FloatField(default=0.0)
    dca_last_decision_json = fields.TextField(null=True)
    automation_paused = fields.BooleanField(default=False)
    automation_paused_at = fields.TextField(null=True)
    reserved_reentry_quote = fields.FloatField(default=0.0)
    waiting_reference_price = fields.FloatField(default=0.0)
    waiting_reference_amount = fields.FloatField(default=0.0)
    waiting_reference_quote = fields.FloatField(default=0.0)
    virtual_waiting_profit = fields.FloatField(default=0.0)
    virtual_waiting_profit_percent = fields.FloatField(default=0.0)
    last_transition_at = fields.TextField(null=True)
