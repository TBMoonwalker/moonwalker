"""Token listing date cache model."""

from tortoise import fields
from tortoise.models import Model


class Listings(Model):
    """Cached listing dates for tokens."""

    id = fields.IntField(pk=True)
    symbol = fields.CharField(max_length=50)
    listing_date = fields.DatetimeField()

    class Meta:
        table = "token_listings"
