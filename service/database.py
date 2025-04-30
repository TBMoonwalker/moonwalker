import helper
from tortoise import Tortoise

logging = helper.LoggerFactory.get_logger("logs/moonwalker.log", "database")


class Database:
    def __init__(self):
        self.db_file = "trades.sqlite"
        logging.info("Initialized")

    async def init(self):
        await Tortoise.init(
            db_url=f"sqlite://db/{self.db_file}",
            modules={"models": ["model"]},
        )
        # Generate the schema
        await Tortoise.generate_schemas()

    async def shutdown(self):
        await Tortoise.close_connections()
