from tortoise import Tortoise, run_async
from logger import Logger


class Database:
    def __init__(self, db_file):
        # Logging
        self.logging = Logger("main")
        self.logging.info("Database module: Initialize database connection")
        self.db_file = db_file

    async def init(self):
        await Tortoise.init(
            db_url=f"sqlite://{self.db_file}", modules={"models": ["models"]}
        )
        # Generate the schema
        await Tortoise.generate_schemas()

    async def shutdown(self):
        await Tortoise.close_connections()
