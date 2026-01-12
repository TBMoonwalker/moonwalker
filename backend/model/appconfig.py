from tortoise import fields
from tortoise.models import Model


class AppConfig(Model):
    id = fields.IntField(pk=True)
    key = fields.CharField(max_length=255, unique=True)
    value = fields.CharField(max_length=1000, null=True)
    value_type = fields.CharField(
        max_length=50, null=True
    )  # 'int', 'float', 'bool', 'str'
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "config"
