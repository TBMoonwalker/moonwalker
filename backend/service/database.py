import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import helper
from tortoise import Tortoise
from tortoise.context import TortoiseContext

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
        self._ctx: TortoiseContext | None = None
        logging.info("Database instance initialized")

    async def init(self) -> None:
        """Initialize the database connection and generate schemas.

        Sets up the Tortoise ORM connection and creates all database tables
        based on the model definitions.

        Raises:
            Exception: If database initialization fails.
        """
        try:
            db_url = os.getenv("MOONWALKER_DB_URL", f"sqlite://db/{self.db_file}")
            self._ctx = await Tortoise.init(
                db_url=db_url,
                modules={"models": ["model"]},
                _enable_global_fallback=True,
            )
            # Generate the schema
            await Tortoise.generate_schemas()
            logging.info("Database initialized successfully")
        except Exception as exc:  # noqa: BLE001 - Catch all exceptions during init
            logging.error("Failed to initialize database: %s", exc, exc_info=True)
            raise

    @asynccontextmanager
    async def context(self):
        """Provide a mandatory Tortoise context."""
        if self._ctx is None:
            raise RuntimeError("Tortoise context is not initialized")
        self._ctx.__enter__()
        try:
            yield
        finally:
            self._ctx.__exit__(None, None, None)

    async def run_with_context(
        self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
    ) -> Any:
        """Run an async callable inside a mandatory Tortoise context."""
        async with self.context():
            return await func(*args, **kwargs)

    async def shutdown(self) -> None:
        """Close all database connections.

        Properly shuts down the Tortoise ORM connection pool and releases
        all database resources.

        Raises:
            Exception: If connection shutdown fails.
        """
        try:
            if self._ctx is not None:
                await self._ctx.close_connections()
                self._ctx = None
            else:
                await Tortoise.close_connections()
            logging.info("Database connections closed successfully")
        except Exception as exc:  # noqa: BLE001 - Catch all exceptions during shutdown
            logging.error(
                "Failed to close database connections: %s", exc, exc_info=True
            )
            raise
