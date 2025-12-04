from tortoise import fields
from tortoise.models import Model


class Listings(Model):
    id = fields.IntField(pk=True)
    symbol = fields.CharField(max_length=50)
    listing_date = fields.DatetimeField()

    class Meta:
        table = "token_listings"
