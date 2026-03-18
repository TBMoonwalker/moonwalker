"""Configuration management for runtime settings."""

import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable

import helper
from model import AppConfig
from service.config_persistence import should_persist_config_value
from service.config_runtime_store import (
    ConfigEntry,
    ConfigRuntimeStore,
    ConfigUpdateAction,
)
from service.redis import CONFIG_CHANNEL, redis_client
from service.strategy_capability import filter_supported_strategies

logging = helper.LoggerFactory.get_logger("logs/config.log", "config")
BACKEND_ROOT = Path(__file__).resolve().parent.parent

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

DEFAULT_CONFIG_VALUES = {
    "tp_spike_confirm_enabled": False,
    "tp_spike_confirm_seconds": 3.0,
    "tp_spike_confirm_ticks": 0,
    "autopilot_green_phase_enabled": False,
    "autopilot_green_phase_ramp_days": 30,
    "autopilot_green_phase_eval_interval_sec": 60,
    "autopilot_green_phase_window_minutes": 60,
    "autopilot_green_phase_min_profitable_close_ratio": 0.8,
    "autopilot_green_phase_speed_multiplier": 1.5,
    "autopilot_green_phase_exit_multiplier": 1.15,
    "autopilot_green_phase_max_extra_deals": 2,
    "autopilot_green_phase_confirm_cycles": 2,
    "autopilot_green_phase_release_cycles": 4,
    "autopilot_green_phase_max_locked_fund_percent": 85.0,
}


def resolve_timeframe(config: dict[str, Any], default: str = "1m") -> str:
    """Resolve the effective bot timeframe from the canonical key."""
    value = config.get("timeframe")
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


def resolve_history_lookback_days(
    config: dict[str, Any],
    timeframe: str | None = None,
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

    effective_timeframe = timeframe or resolve_timeframe(config)
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

        Creates an empty typed runtime store and subscriber set. The listener task
        is created during instance initialization via the instance() classmethod.
        """
        self._store = ConfigRuntimeStore()
        self._subscribers: set[Callable[[dict[str, Any]], None]] = set()
        self._listener_task: asyncio.Task | None = None
        self._instance_id = uuid.uuid4().hex

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
        entries: list[ConfigEntry] = []
        rows = await AppConfig.all()
        for row in rows:
            entries.append(self.__build_entry(row.key, row.value, row.value_type))
        self._store.replace_entries(entries)
        self.__refresh_runtime_metadata()

    async def __load_keys(self, keys: list[str]) -> None:
        """Refresh only the specified config keys from the database cache source."""
        normalized_keys = [str(key).strip() for key in keys if str(key).strip()]
        if not normalized_keys:
            return

        rows = await AppConfig.filter(key__in=normalized_keys)
        loaded_keys = set()
        for row in rows:
            self._store.upsert_entry(
                self.__build_entry(row.key, row.value, row.value_type)
            )
            loaded_keys.add(row.key)

        for key in normalized_keys:
            if key not in loaded_keys:
                self._store.remove_entry(key)

        self.__refresh_runtime_metadata()

    def __refresh_runtime_metadata(self) -> None:
        """Refresh derived config metadata that is not stored in AppConfig."""
        self._store.set_metadata(
            {
                "strategies": self.__get_strategies(),
                "signal_plugins": self.__get_signal_plugins(),
            }
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

    def snapshot(self) -> dict[str, Any]:
        """Return a defensive copy of the current config state."""
        return self._store.snapshot(defaults=DEFAULT_CONFIG_VALUES)

    def __notify_subscribers(self) -> None:
        """Notify local subscribers that cache values changed."""
        for subscriber in self._subscribers:
            subscriber(self.snapshot())

    async def __clear_key(self, key: str) -> bool:
        """Remove a config key from persistent storage and the in-memory cache."""
        deleted_count = await AppConfig.filter(key=key).delete()
        existed_in_cache = self._store.remove_entry(key)
        return bool(deleted_count or existed_in_cache)

    async def __publish_change(self, keys: list[str]) -> None:
        """Publish config changes to Redis if available.

        Redis publish failures should not roll back DB writes.
        """
        if not keys:
            return

        message = json.dumps(
            {
                "source": self._instance_id,
                "keys": [str(key).strip() for key in keys if str(key).strip()],
            }
        )
        try:
            await redis_client.publish(CONFIG_CHANNEL, message)
        except Exception as exc:  # noqa: BLE001 - Keep local updates working.
            logging.warning("Failed to publish config change for '%s': %s", keys, exc)

    def __parse_update_payload(self, payload: Any) -> dict[str, Any]:
        """Normalize update payloads from API clients.

        Supports both legacy stringified JSON values and direct dict payloads.
        """
        parsed = json.loads(payload) if isinstance(payload, str) else payload
        if not isinstance(parsed, dict):
            raise TypeError("Config payload must be a JSON object")
        if "type" not in parsed or "value" not in parsed:
            raise KeyError("Config payload must include 'type' and 'value'")
        return parsed

    def __build_entry(
        self,
        key: str,
        serialized_value: Any,
        value_type: str,
    ) -> ConfigEntry:
        """Build one typed runtime cache entry from stored config data."""
        return ConfigEntry(
            key=key,
            value_type=value_type,
            value=self.__set_type(serialized_value, value_type),
        )

    def __build_update_action(
        self,
        key: str,
        raw_value: Any,
    ) -> ConfigUpdateAction:
        """Normalize one incoming config mutation into a typed action."""
        update = self.__parse_update_payload(raw_value)
        value_type = str(update["type"]).strip()
        value_data = update["value"]
        should_persist = should_persist_config_value(value_type, value_data)
        if not should_persist:
            return ConfigUpdateAction(
                key=key,
                value_type=value_type,
                persist=False,
                serialized_value=None,
                runtime_value=None,
            )

        serialized_value = self.__serialize_value_for_storage(value_data, value_type)
        return ConfigUpdateAction(
            key=key,
            value_type=value_type,
            persist=True,
            serialized_value=serialized_value,
            runtime_value=self.__set_type(serialized_value, value_type),
        )

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
        return self._store.get(key, defaults=DEFAULT_CONFIG_VALUES, default=default)

    async def set(self, key: str, value: Any) -> bool:
        """Set a configuration value in the database and notify subscribers.

        Args:
            key: The configuration key to set
            value: Update payload containing "value" and "type" keys

        Returns:
            True if the operation succeeded
        """
        action = self.__build_update_action(key, value)
        if not action.persist:
            changed = await self.__clear_key(key)
            if changed:
                self.__notify_subscribers()
                await self.__publish_change([key])
            return True

        await AppConfig.update_or_create(
            key=key,
            defaults={
                "value": action.serialized_value,
                "value_type": action.value_type,
            },
        )
        entry = action.to_entry()
        if entry is not None:
            self._store.upsert_entry(entry)
        self.__notify_subscribers()
        # Notify all subscribers across processes (best effort)
        await self.__publish_change([key])

        return True

    async def batch_set(self, updates: dict[str, Any]) -> bool:
        """Update multiple configuration keys in the database at once.

        Args:
            updates: Dictionary of key-value pairs where values are JSON strings

        Returns:
            True if the operation succeeded
        """
        changed_keys: list[str] = []
        for key, raw_value in updates.items():
            try:
                action = self.__build_update_action(key, raw_value)
            except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                logging.warning(
                    "Skipping invalid config payload for '%s': %s", key, exc
                )
                continue

            if action.persist:
                await AppConfig.update_or_create(
                    key=key,
                    defaults={
                        "value": action.serialized_value,
                        "value_type": action.value_type,
                    },
                )
                entry = action.to_entry()
                if entry is not None:
                    self._store.upsert_entry(entry)
                changed_keys.append(key)
            elif await self.__clear_key(key):
                changed_keys.append(key)

        if changed_keys:
            self.__notify_subscribers()
            await self.__publish_change(changed_keys)

        return True

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Subscribe a callback function to configuration changes.

        The callback will be called with a defensive copy of the configuration
        state whenever a configuration change is detected.

        Args:
            callback: A callable that takes a dictionary of configuration values
        """
        self._subscribers.add(callback)

    async def reload(self, keys: list[str] | None = None) -> None:
        """Reload all configuration from the database and notify subscribers.

        This method is called automatically when a configuration change is detected
        via the Redis pub/sub channel, or can be called manually to force a reload.
        """
        if keys:
            await self.__load_keys(keys)
        else:
            await self.load_all()
        self.__notify_subscribers()

    async def _handle_change_message(self, payload: Any) -> None:
        """Apply a Redis change payload, skipping self-originated updates."""
        keys: list[str] | None = None
        source = None

        if isinstance(payload, str):
            stripped = payload.strip()
            if stripped:
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    keys = [stripped]
                else:
                    if isinstance(parsed, dict):
                        source = parsed.get("source")
                        raw_keys = parsed.get("keys")
                        if isinstance(raw_keys, list):
                            keys = [
                                str(key).strip() for key in raw_keys if str(key).strip()
                            ]
                    elif isinstance(parsed, list):
                        keys = [str(key).strip() for key in parsed if str(key).strip()]

        if source == self._instance_id:
            return

        if keys:
            await self.reload(keys)
            return

        await self.reload()

    async def _listen(self) -> None:
        """Listen for configuration change notifications via Redis pub/sub.

        This internal method runs as a background task and reloads the configuration
        whenever a message is received on the CONFIG_CHANNEL.
        """
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(CONFIG_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] == "message":
                await self._handle_change_message(message.get("data"))

    def __get_filenames_in_directory(
        self, directory: str, sort: bool = True
    ) -> list[str]:
        """Get a list of filenames in the specified directory.

        Args:
            directory: The path to the directory relative to the backend root.
            sort: Whether to sort the filenames alphabetically. Default is True.

        Returns:
            List of filenames (without extensions) found in the directory

        Raises:
            ValueError: If the specified path is not a valid directory
            IOError: If an error occurs while reading the directory
        """
        directory_path = BACKEND_ROOT / directory
        if not directory_path.is_dir():
            raise ValueError(
                f"The specified path '{directory_path}' is not a valid directory."
            )

        # Get all file paths matching the pattern
        try:
            all_files = []
            for root, dirs, files in os.walk(directory_path):
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
        except OSError as e:
            raise IOError(f"An error occurred while reading the directory: {str(e)}")

        # Extract just the filenames
        filenames = [os.path.splitext(os.path.basename(file))[0] for file in all_files]

        # Sort if requested
        if sort:
            filenames.sort()

        return filenames
