from tortoise import fields
from tortoise.models import Model


class Indicators(Model):
    date = fields.TextField()
    indicator = fields.TextField()
    value = fields.FloatField()

    def __dict__(self):
        return f"'id': {self.id}, 'date': {self.date}, 'indicator': {self.indicator}, 'value': {self.value}"
