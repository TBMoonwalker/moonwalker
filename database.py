from tortoise import Tortoise, run_async
from logger import LoggerFactory


class Database:
    def __init__(self, db_file, loglevel):
        # Logging
        self.logging = LoggerFactory.get_logger(
            "moonwalker.log", "database", log_level=loglevel
        )
        self.logging.info("Initialized")
        self.db_file = db_file

    async def init(self):
        await Tortoise.init(
            db_url=f"sqlite://{self.db_file}", modules={"models": ["models"]}
        )
        # Generate the schema
        await Tortoise.generate_schemas()

    async def shutdown(self):
        await Tortoise.close_connections()
