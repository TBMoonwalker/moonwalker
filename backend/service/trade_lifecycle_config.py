"""Shared structured validation errors for config, backup, and restore paths."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TradeModeConfigErrorCode(StrEnum):
    """Stable config validation error codes."""

    INVALID_BACKUP_SHAPE = "invalid_backup_shape"


@dataclass(frozen=True)
class TradeModeErrorPayload:
    """Structured operator-safe config validation payload."""

    code: str
    source: str
    message: str
    safe_fields: dict[str, Any]
    next_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the public JSON payload for API responses."""
        payload = {
            "code": self.code,
            "source": self.source,
            "message": self.message,
            "safe_fields": dict(self.safe_fields),
        }
        if self.next_action is not None:
            payload["next_action"] = self.next_action
        return payload


class TradeModeConfigError(ValueError):
    """Structured validation error shared across startup, save, and restore."""

    def __init__(
        self,
        payload: TradeModeErrorPayload,
        *,
        status_code: int = 409,
    ) -> None:
        super().__init__(payload.message)
        self.payload = payload
        self.status_code = status_code

    def to_response_body(self) -> dict[str, Any]:
        """Return a legacy-safe API response body with structured details."""
        payload = self.payload.to_dict()
        return {
            "error": payload["message"],
            "message": payload["message"],
            "migration_error": payload,
        }


def build_invalid_backup_shape_error(
    *,
    source: str = "restore",
    message: str,
    safe_fields: dict[str, Any] | None = None,
) -> TradeModeConfigError:
    """Build the shared invalid-backup-shape error payload."""
    return TradeModeConfigError(
        TradeModeErrorPayload(
            code=TradeModeConfigErrorCode.INVALID_BACKUP_SHAPE.value,
            source=source,
            message=message,
            safe_fields=safe_fields or {},
        ),
        status_code=400,
    )
