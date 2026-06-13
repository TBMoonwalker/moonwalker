"""AI trust cockpit prediction ledger model."""

from tortoise import fields
from tortoise.models import Model


class AiTrustPrediction(Model):
    """Persist shadow AI observations for later calibration."""

    id = fields.IntField(primary_key=True)
    symbol = fields.CharField(max_length=50)
    deal_id = fields.CharField(max_length=36, null=True)
    trade_id = fields.IntField(null=True)
    event_timestamp = fields.TextField(null=True)
    source_event = fields.CharField(max_length=64)
    provider = fields.CharField(max_length=32, default="ollama")
    model_name = fields.CharField(max_length=128, null=True)
    prompt_version = fields.CharField(max_length=32, default="ai_trust_v1")
    schema_version = fields.CharField(max_length=32, default="1")
    status = fields.CharField(max_length=32, default="unscored")
    provider_status = fields.CharField(max_length=64, default="unscored")
    risk_score = fields.IntField(null=True)
    confidence = fields.FloatField(null=True)
    would_warn = fields.BooleanField(null=True)
    warning_severity = fields.CharField(max_length=16, default="none")
    reason_codes_json = fields.TextField(default="[]")
    operator_note = fields.TextField(null=True)
    feature_bundle_json = fields.TextField(default="{}")
    outcome_status = fields.CharField(max_length=32, default="open")
    bad_entry = fields.BooleanField(null=True)
    bad_entry_reasons_json = fields.TextField(default="[]")
    outcome_profit = fields.FloatField(null=True)
    outcome_profit_percent = fields.FloatField(null=True)
    outcome_duration_hours = fields.FloatField(null=True)
    outcome_so_count = fields.IntField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "ai_trust_predictions"
        indexes = (
            ("created_at",),
            ("deal_id",),
            ("symbol", "created_at"),
            ("status", "provider_status"),
            ("outcome_status", "bad_entry"),
        )
