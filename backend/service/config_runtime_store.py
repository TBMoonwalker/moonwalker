"""Internal runtime store for config entries, defaults, and derived metadata."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class ConfigEntry:
    """Typed persisted config entry cached in memory."""

    key: str
    value_type: str
    value: Any


@dataclass(frozen=True)
class ConfigUpdateAction:
    """Normalized config mutation ready for persistence or clearing."""

    key: str
    value_type: str
    persist: bool
    serialized_value: Any | None
    runtime_value: Any | None

    def to_entry(self) -> ConfigEntry | None:
        """Convert a persisted update into a cache entry."""
        if not self.persist:
            return None
        return ConfigEntry(
            key=self.key,
            value_type=self.value_type,
            value=self.runtime_value,
        )


class ConfigRuntimeStore:
    """Keep persisted config entries separate from defaults and metadata."""

    def __init__(self) -> None:
        self._entries: dict[str, ConfigEntry] = {}
        self._metadata: dict[str, Any] = {}

    def replace_entries(self, entries: Iterable[ConfigEntry]) -> None:
        """Replace all persisted entries with a new typed snapshot."""
        self._entries = {entry.key: entry for entry in entries}

    def upsert_entry(self, entry: ConfigEntry) -> None:
        """Insert or replace one persisted entry."""
        self._entries[entry.key] = entry

    def remove_entry(self, key: str) -> bool:
        """Remove one persisted entry by key."""
        return self._entries.pop(key, None) is not None

    def set_metadata(self, metadata: Mapping[str, Any]) -> None:
        """Replace derived runtime metadata with a defensive copy."""
        self._metadata = copy.deepcopy(dict(metadata))

    def get(
        self,
        key: str,
        *,
        defaults: Mapping[str, Any],
        default: Any | None = None,
    ) -> Any | None:
        """Return one runtime config value with persisted-first precedence."""
        entry = self._entries.get(key)
        if entry is not None:
            return copy.deepcopy(entry.value)
        if key in self._metadata:
            return copy.deepcopy(self._metadata[key])
        if key in defaults:
            return copy.deepcopy(defaults[key])
        return default

    def snapshot(self, *, defaults: Mapping[str, Any]) -> dict[str, Any]:
        """Return a merged runtime snapshot for subscribers and consumers."""
        snapshot = copy.deepcopy(dict(defaults))
        for key, entry in self._entries.items():
            snapshot[key] = copy.deepcopy(entry.value)
        snapshot.update(copy.deepcopy(self._metadata))
        return snapshot
