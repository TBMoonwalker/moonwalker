import asyncio
import os
import helper
import json
from typing import Any, Callable, Dict, Set, Optional
from model import AppConfig
from service.redis import redis_client, CONFIG_CHANNEL

logging = helper.LoggerFactory.get_logger("logs/config.log", "config")


class Config:
    """Configuration management class that handles loading, storing, and subscribing to configuration changes.

    This class implements the Singleton pattern to ensure a single instance across the application.
    It supports configuration caching, change notifications, and Redis-based pub/sub for distributed
    configuration management.
    """
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self):
        """Initialize the Config instance.

        Creates empty cache and subscriber set. The listener task is created during instance
        initialization via the instance() classmethod.
        """
        self._cache: Dict[str, Any] = {}
        self._subscribers: Set[Callable[[Dict[str, Any]], None]] = set()
        self._listener_task: Optional[asyncio.Task] = None

    @classmethod
    async def instance(cls) -> "Config":
        """Get or create the Config singleton instance.

        Uses asyncio.Lock to ensure thread-safe creation of the singleton instance.
        Loads all configuration on first creation and starts the Redis listener task.

        Returns:
            Config: The singleton Config instance
        """
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                await cls._instance.load_all()
                cls._instance._listener_task = asyncio.create_task(
                    cls._instance._listen()
                )
            return cls._instance

    async def load_all(self):
        """Load all configuration from the database into the cache.

        Retrieves all AppConfig entries and converts their values to the appropriate types
        based on the value_type field. Also loads strategies and signal plugins.
        """
        rows = await AppConfig.all()
        for row in rows:
            value = self.__set_type(row.value, row.value_type)
            self._cache[row.key] = value
        # get strategies
        self._cache["strategies"] = self.__get_strategies()
        # get signal plugins
        self._cache["signal_plugins"] = self.__get_signal_plugins()

    def __set_type(self, value: str, type: str) -> Any:
        """Convert a string value to its appropriate Python type based on the type specification.

        Args:
            value: The string value to convert
            type: The type specification ("int", "float", "bool", or any other string for str)

        Returns:
            The converted value in the appropriate Python type
        """
        if type == "int":
            return int(value)
        elif type == "float":
            return float(value)
        elif type == "bool":
            return bool(value)
        else:
            return value


    def __get_strategies(self) -> list[str]:
        """Get a list of available strategy filenames from the strategies directory.

        Returns:
            List of strategy names (without .py extension) sorted alphabetically
        """
        strategies = self.__get_filenames_in_directory("strategies")
        return strategies

    def __get_signal_plugins(self) -> list[str]:
        """Get a list of available signal plugin filenames from the signals directory.

        Returns:
            List of signal plugin names (without .py extension) sorted alphabetically
        """
        signal_plugins = self.__get_filenames_in_directory("signals")
        return signal_plugins


    def get(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        """Get a configuration value by key.

        Args:
            key: The configuration key to retrieve
            default: Optional default value to return if key is not found

        Returns:
            The configuration value or default if key not found
        """
        return self._cache.get(key, default)

    async def set(self, key: str, value: Dict[str, Any]) -> bool:
        """Set a configuration value in the database and notify subscribers.

        Args:
            key: The configuration key to set
            value: Dictionary containing "value" and "type" keys

        Returns:
            True if the operation succeeded
        """
        await AppConfig.update_or_create(key=key, defaults={"value": value["value"], "value_type": value["type"]})
        # Notify all subscribers across processes
        await redis_client.publish(CONFIG_CHANNEL, key)

        return True

    async def batch_set(self, updates: Dict[str, Any]) -> bool:
        """Update multiple configuration keys in the database at once.

        Args:
            updates: Dictionary of key-value pairs where values are JSON strings

        Returns:
            True if the operation succeeded
        """
        for key, value in updates.items():
            value = json.loads(value)
            if value["value"]:
                await AppConfig.update_or_create(key=key, defaults={"value": value["value"], "value_type": value["type"]})
        # Notify all subscribers across processes
        # ToDo - create an Array as String with changed files instead of "multiple"
        await redis_client.publish(CONFIG_CHANNEL, "multiple")

        return True

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Subscribe a callback function to configuration changes.

        The callback will be called with the full configuration cache whenever
        a configuration change is detected.

        Args:
            callback: A callable that takes a dictionary of configuration values
        """
        self._subscribers.add(callback)

    async def reload(self) -> None:
        """Reload all configuration from the database and notify subscribers.

        This method is called automatically when a configuration change is detected
        via the Redis pub/sub channel, or can be called manually to force a reload.
        """
        await self.load_all()
        for subscriber in self._subscribers:
            subscriber(self._cache)

    async def _listen(self) -> None:
        """Listen for configuration change notifications via Redis pub/sub.

        This internal method runs as a background task and reloads the configuration
        whenever a message is received on the CONFIG_CHANNEL.
        """
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(CONFIG_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] == "message":
                await self.reload()

    def __get_filenames_in_directory(self, directory: str, sort: bool = True) -> list[str]:
        """Get a list of filenames in the specified directory.

        Args:
            directory: The path to the directory (relative to current working directory)
            sort: Whether to sort the filenames alphabetically. Default is True.

        Returns:
            List of filenames (without extensions) found in the directory

        Raises:
            ValueError: If the specified path is not a valid directory
            IOError: If an error occurs while reading the directory
        """
        directory = os.getcwd() + "/" + directory
        if not os.path.isdir(directory):
            raise ValueError(f"The specified path '{directory}' is not a valid directory.")

        # Create the pattern based on recursive flag
        pattern = "*"

        # Get all file paths matching the pattern
        try:
            all_files = []
            for root, dirs, files in os.walk(directory):
                # Exclude certain directories
                dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
                for file in files:
                    full_path = os.path.join(root, file)
                    if os.path.isfile(full_path):
                        all_files.append(full_path)
        except Exception as e:
            raise IOError(f"An error occurred while reading the directory: {str(e)}")

        # Extract just the filenames
        filenames = [os.path.splitext(os.path.basename(file))[0] for file in all_files]

        # Sort if requested
        if sort:
            filenames.sort()

        return filenames