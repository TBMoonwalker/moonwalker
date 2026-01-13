import asyncio
import os
import helper
import json
from typing import Any, Callable, Dict, Set
from model import AppConfig
from service.redis import redis_client, CONFIG_CHANNEL

logging = helper.LoggerFactory.get_logger("logs/config.log", "config")


class Config:
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._subscribers: Set[Callable[[Dict[str, Any]], None]] = set()
        self._listener_task: asyncio.Task | None = None

    @classmethod
    async def instance(cls) -> "Config":
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                await cls._instance.load_all()
                cls._instance._listener_task = asyncio.create_task(
                    cls._instance._listen()
                )
            return cls._instance

    async def load_all(self):
        rows = await AppConfig.all()
        for row in rows:
            value = self.__set_type(row.value, row.value_type)
            self._cache[row.key] = value
        # get strategies
        self._cache["strategies"] = self.__get_strategies()
        # get signal plugins
        self._cache["signal_plugins"] = self.__get_signal_plugins()

    def __set_type(self, value, type):
        if type == "int":
            return int(value)
        elif type == "float":
            return float(value)
        elif type == "bool":
            return bool(value)
        else:
            return value


    def __get_strategies(self):
        strategies = self.__get_filenames_in_directory("strategies")
        return strategies

    def __get_signal_plugins(self):
        signal_plugins = self.__get_filenames_in_directory("signals")
        return signal_plugins


    def get(self, key: str, default=None):
        return self._cache.get(key, default)

    async def set(self, key: str, value: Dict):
        await AppConfig.update_or_create(key=key, defaults={"value": value["value"], "value_type": value["type"]})
        # Notify all subscribers across processes
        await redis_client.publish(CONFIG_CHANNEL, key)

        return True

    async def batch_set(self, updates: Dict[str, Any]):
        """
        Update multiple config keys in the database at once.
        """
        for key, value in updates.items():
            value = json.loads(value)
            logging.info(value["value"])
            logging.info(value["type"])
            if value["value"]:
                await AppConfig.update_or_create(key=key, defaults={"value": value["value"], "value_type": value["type"]})
        # Notify all subscribers across processes
        # ToDo - create an Array as String with changed files instead of "multiple"
        await redis_client.publish(CONFIG_CHANNEL, "multiple")

        return True

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]):
        self._subscribers.add(callback)

    async def reload(self):
        await self.load_all()
        for subscriber in self._subscribers:
            subscriber(self._cache)

    async def _listen(self):
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(CONFIG_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] == "message":
                await self.reload()

    def __get_filenames_in_directory(self,directory, sort=True):
        """
        Get a list of filenames in the specified directory.

        Args:
            directory (str): The path to the directory.
            recursive (bool): Whether to include files from subdirectories. Default is False.
            sort (bool): Whether to sort the filenames. Default is True.

        Returns:
            list: A list of filenames in the directory.
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