"""Typed normalization for abbreviated external market-volume values."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

_ABBREVIATED_VOLUME = re.compile(
    r"^(?P<size>(?:\d+(?:\.\d*)?|\.\d+))(?P<unit>[kKmMbB])$"
)
_PLAIN_VOLUME_NUMBER = re.compile(r"^(?:\d+(?:\.\d*)?|\.\d+)$")
_NUMERIC_UNITS = (
    ("B", 1_000_000_000.0),
    ("M", 1_000_000.0),
    ("K", 1_000.0),
)


@dataclass(frozen=True)
class ExternalVolume:
    """Normalized volume compatible with Moonwalker's volume filter."""

    unit: str
    size: float


@dataclass(frozen=True)
class ExternalVolumeParseResult:
    """Parsed volume or a stable source-specific rejection reason."""

    volume: ExternalVolume | None
    reason_code: str | None


def parse_external_volume(value: Any) -> ExternalVolumeParseResult:
    """Normalize numeric base-unit volumes or explicit K/M/B abbreviations."""
    if isinstance(value, bool) or value is None:
        return ExternalVolumeParseResult(None, "symsignals_volume_invalid_type")

    if isinstance(value, (int, float)):
        numeric = float(value)
        if not math.isfinite(numeric):
            return ExternalVolumeParseResult(None, "symsignals_volume_nonfinite")
        if numeric < 0:
            return ExternalVolumeParseResult(None, "symsignals_volume_negative")
        for unit, divisor in _NUMERIC_UNITS:
            if numeric >= divisor:
                return ExternalVolumeParseResult(
                    ExternalVolume(unit=unit, size=numeric / divisor),
                    None,
                )
        return ExternalVolumeParseResult(None, "symsignals_volume_missing_unit")

    if not isinstance(value, str):
        return ExternalVolumeParseResult(None, "symsignals_volume_invalid_type")

    normalized = value.strip()
    match = _ABBREVIATED_VOLUME.fullmatch(normalized)
    if match is None:
        if _PLAIN_VOLUME_NUMBER.fullmatch(normalized):
            return ExternalVolumeParseResult(None, "symsignals_volume_missing_unit")
        return ExternalVolumeParseResult(None, "symsignals_volume_malformed")

    size = float(match.group("size"))
    if not math.isfinite(size):
        return ExternalVolumeParseResult(None, "symsignals_volume_nonfinite")
    return ExternalVolumeParseResult(
        ExternalVolume(unit=match.group("unit").upper(), size=size),
        None,
    )
