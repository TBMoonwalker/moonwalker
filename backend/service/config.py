"""Configuration management for runtime settings."""

import asyncio
import json
import os
import re
from typing import Any, Callable

import helper
from model import AppConfig
from service.redis import CONFIG_CHANNEL, redis_client
from service.strategy_capability import filter_supported_strategies

logging = helper.LoggerFactory.get_logger("logs/config.log", "config")

TIMEFRAME_KEYS = (
    "timeframe",
    "signal_strategy_timeframe",
    "dca_strategy_timeframe",
    "tp_strategy_timeframe",
)

HISTORY_LOOKBACK_DEFAULTS_BY_TIMEFRAME = {
    "1m": "30d",
    "15m": "90d",
    "1h": "180d",
    "4h": "1y",
    "1d": "3y",
}

HISTORY_LOOKBACK_UNIT_TO_DAYS = {
    "d": 1,
    "w": 7,
    "m": 30,
    "y": 365,
}


def resolve_timeframe(
    config: dict[str, Any], preferred_key: str | None = None, default: str = "1m"
) -> str:
    """Resolve the effective bot timeframe from canonical and legacy keys."""
    candidate_keys: list[str] = []
    if preferred_key:
        candidate_keys.append(preferred_key)
    candidate_keys.extend(TIMEFRAME_KEYS)
    for key in candidate_keys:
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def parse_history_lookback_to_days(value: Any) -> int | None:
    """Parse lookback text like 30d/12w/6m/1y into days."""
    if value is None:
        return None

    raw = str(value).strip().lower()
    if not raw or raw in {"false", "none", "null"}:
        return None

    if raw.isdigit():
        days = int(raw)
        return days if days > 0 else None

    match = re.fullmatch(r"(\d+)\s*([dwmy])", raw)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        return None

    return amount * HISTORY_LOOKBACK_UNIT_TO_DAYS[unit]


def format_history_lookback_days(days: int) -> str:
    """Format day count into canonical lookback string."""
    normalized_days = max(1, int(days))
    if normalized_days % 365 == 0:
        return f"{normalized_days // 365}y"
    if normalized_days % 30 == 0:
        return f"{normalized_days // 30}m"
    if normalized_days % 7 == 0:
        return f"{normalized_days // 7}w"
    return f"{normalized_days}d"


def resolve_history_lookback_days(
    config: dict[str, Any],
    timeframe: str | None = None,
    preferred_timeframe_key: str | None = None,
) -> int:
    """Resolve unified history lookback days with legacy fallback.

    Precedence:
    1) `history_lookback_time` (new canonical key)
    2) `history_from_data` (legacy numeric days)
    3) best-practice defaults by resolved timeframe
    """
    parsed = parse_history_lookback_to_days(config.get("history_lookback_time"))
    if parsed:
        return parsed

    legacy_days = parse_history_lookback_to_days(config.get("history_from_data"))
    if legacy_days:
        return legacy_days

    effective_timeframe = timeframe or resolve_timeframe(
        config, preferred_key=preferred_timeframe_key
    )
    default_window = HISTORY_LOOKBACK_DEFAULTS_BY_TIMEFRAME.get(
        str(effective_timeframe).strip().lower(), "90d"
    )
    default_days = parse_history_lookback_to_days(default_window)
    return default_days or 90


class Config:
    """Configuration management class that handles loading, storing, and subscribing to configuration changes.

    This class implements the Singleton pattern to ensure a single instance across the application.
    It supports configuration caching, change notifications, and Redis-based pub/sub for distributed
    configuration management.
    """

    _instance = None
    _lock = asyncio.Lock()

    def __init__(self) -> None:
        """Initialize the Config instance.

        Creates empty cache and subscriber set. The listener task is created during instance
        initialization via the instance() classmethod.
        """
        self._cache: dict[str, Any] = {}
        self._subscribers: set[Callable[[dict[str, Any]], None]] = set()
        self._listener_task: asyncio.Task | None = None

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

    async def load_all(self) -> None:
        """Load all configuration from the database into the cache.

        Retrieves all AppConfig entries and converts their values to the appropriate types
        based on the value_type field. Also loads strategies and signal plugins.
        """
        rows = await AppConfig.all()
        for row in rows:
            value = self.__set_type(row.value, row.value_type)
            self._cache[row.key] = value
        await self.__migrate_legacy_timeframe_if_needed()
        # get strategies
        self._cache["strategies"] = self.__get_strategies()
        # get signal plugins
        self._cache["signal_plugins"] = self.__get_signal_plugins()

    async def __migrate_legacy_timeframe_if_needed(self) -> None:
        """Backfill canonical timeframe from legacy keys when missing.

        This keeps old installations working after moving to the unified `timeframe`
        key while allowing new clients to stop writing legacy timeframe keys.
        """
        canonical = self._cache.get("timeframe")
        if isinstance(canonical, str) and canonical.strip():
            return

        legacy_timeframe = None
        for key in TIMEFRAME_KEYS[1:]:
            value = self._cache.get(key)
            if isinstance(value, str) and value.strip():
                legacy_timeframe = value.strip()
                break

        if not legacy_timeframe:
            return

        self._cache["timeframe"] = legacy_timeframe
        await AppConfig.update_or_create(
            key="timeframe",
            defaults={"value": legacy_timeframe, "value_type": "str"},
        )
        logging.info(
            "Migrated legacy timeframe configuration to canonical key 'timeframe': %s",
            legacy_timeframe,
        )

    def __set_type(self, value: str, type: str) -> Any:
        """Convert a string value to its appropriate Python type based on the type specification.

        Args:
            value: The string value to convert
            type: The type specification ("int", "float", "bool", or any other string for str)

        Returns:
            The converted value in the appropriate Python type
        """
        if type == "int":
            try:
                if isinstance(value, bool):
                    return int(value)
                normalized = str(value).strip().lower()
                if normalized in {"false", "none", "null", ""}:
                    return 0
                return int(value)
            except (TypeError, ValueError):
                logging.warning(
                    "Invalid int config value '%s'. Falling back to 0.", value
                )
                return 0
        elif type == "float":
            try:
                if isinstance(value, bool):
                    return float(value)
                normalized = str(value).strip().lower()
                if normalized in {"false", "none", "null", ""}:
                    return 0.0
                return float(value)
            except (TypeError, ValueError):
                logging.warning(
                    "Invalid float config value '%s'. Falling back to 0.0.", value
                )
                return 0.0
        elif type == "bool":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "on"}
        else:
            return value

    def __serialize_value_for_storage(self, value: Any, value_type: str) -> Any:
        """Serialize values before storing in AppConfig.

        For `str` typed config, persist dict/list as valid JSON strings so clients
        can parse them with JSON.parse without Python-literal normalization hacks.
        """
        if value_type == "str" and isinstance(value, (dict, list)):
            return json.dumps(value)
        return value

    def __get_strategies(self) -> list[str]:
        """Get a list of available strategy filenames from the strategies directory.

        Returns:
            List of strategy names (without .py extension) sorted alphabetically
        """
        strategies = self.__get_filenames_in_directory("strategies")
        return filter_supported_strategies(strategies)

    def __get_signal_plugins(self) -> list[str]:
        """Get a list of available signal plugin filenames from the signals directory.

        Returns:
            List of signal plugin names (without .py extension) sorted alphabetically
        """
        signal_plugins = self.__get_filenames_in_directory("signals")
        return signal_plugins

    def get(self, key: str, default: Any | None = None) -> Any | None:
        """Get a configuration value by key.

        Args:
            key: The configuration key to retrieve
            default: Optional default value to return if key is not found

        Returns:
            The configuration value or default if key not found
        """
        return self._cache.get(key, default)

    async def set(self, key: str, value: dict[str, Any]) -> bool:
        """Set a configuration value in the database and notify subscribers.

        Args:
            key: The configuration key to set
            value: Dictionary containing "value" and "type" keys

        Returns:
            True if the operation succeeded
        """
        serialized_value = self.__serialize_value_for_storage(
            value["value"], value["type"]
        )
        await AppConfig.update_or_create(
            key=key,
            defaults={"value": serialized_value, "value_type": value["type"]},
        )
        # Notify all subscribers across processes
        await redis_client.publish(CONFIG_CHANNEL, key)

        return True

    async def batch_set(self, updates: dict[str, Any]) -> bool:
        """Update multiple configuration keys in the database at once.

        Args:
            updates: Dictionary of key-value pairs where values are JSON strings

        Returns:
            True if the operation succeeded
        """
        for key, value in updates.items():
            value = json.loads(value)
            value_type = value["type"]
            value_data = value["value"]
            is_numeric_value = isinstance(value_data, (int, float)) and not isinstance(
                value_data, bool
            )
            should_persist = (
                bool(value["value"])
                or (value_type == "bool" and value_data is False)
                or (
                    value_type in {"int", "float"}
                    and is_numeric_value
                    and value_data == 0
                )
            )
            if should_persist:
                serialized_value = self.__serialize_value_for_storage(
                    value_data, value_type
                )
                await AppConfig.update_or_create(
                    key=key,
                    defaults={"value": serialized_value, "value_type": value_type},
                )
        # Notify all subscribers across processes
        # ToDo - create an Array as String with changed files instead of "multiple"
        await redis_client.publish(CONFIG_CHANNEL, "multiple")

        return True

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
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

    def __get_filenames_in_directory(
        self, directory: str, sort: bool = True
    ) -> list[str]:
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
            raise ValueError(
                f"The specified path '{directory}' is not a valid directory."
            )

        # Get all file paths matching the pattern
        try:
            all_files = []
            for root, dirs, files in os.walk(directory):
                # Exclude certain directories
                dirs[:] = [
                    d for d in dirs if not d.startswith(".") and d != "__pycache__"
                ]
                for file in files:
                    if not file.endswith(".py") or file == "__init__.py":
                        continue
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
