import helper
from typing import Any

from tortoise import Tortoise

logging = helper.LoggerFactory.get_logger("logs/database.log", "database")


class Database:
    """Database connection management class for Tortoise ORM.

    Handles initialization, connection management, and shutdown of the database
    connection pool for the application.
    """

    def __init__(self) -> None:
        """Initialize the Database instance.

        Sets the database file name and initializes logging.

        Attributes:
            db_file: Name of the SQLite database file.
        """
        self.db_file = "trades.sqlite"
        logging.info("Database instance initialized")

    async def init(self) -> None:
        """Initialize the database connection and generate schemas.

        Sets up the Tortoise ORM connection and creates all database tables
        based on the model definitions.

        Raises:
            Exception: If database initialization fails.
        """
        try:
            await Tortoise.init(
                db_url=f"sqlite://db/{self.db_file}",
                modules={"models": ["model"]},
            )
            # Generate the schema
            await Tortoise.generate_schemas()
            logging.info("Database initialized successfully")
        except Exception as exc:  # noqa: BLE001 - Catch all exceptions during init
            logging.error("Failed to initialize database: %s", exc, exc_info=True)
            raise

    async def shutdown(self) -> None:
        """Close all database connections.

        Properly shuts down the Tortoise ORM connection pool and releases
        all database resources.

        Raises:
            Exception: If connection shutdown fails.
        """
        try:
            await Tortoise.close_connections()
            logging.info("Database connections closed successfully")
        except Exception as exc:  # noqa: BLE001 - Catch all exceptions during shutdown
            logging.error("Failed to close database connections: %s", exc, exc_info=True)
            raise
