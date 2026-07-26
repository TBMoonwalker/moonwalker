"""Regression coverage for typed SymSignals volume normalization."""

from __future__ import annotations

import math
from typing import Any

import pytest
from service.external_volume import parse_external_volume


@pytest.mark.parametrize(
    ("raw", "unit", "size"),
    [
        ("10k", "K", 10.0),
        ("2.5M", "M", 2.5),
        ("1B", "B", 1.0),
        (25_000, "K", 25.0),
        (2_500_000.0, "M", 2.5),
        (3_000_000_000, "B", 3.0),
    ],
)
def test_parse_external_volume_accepts_documented_values(
    raw: Any,
    unit: str,
    size: float,
) -> None:
    result = parse_external_volume(raw)

    assert result.reason_code is None
    assert result.volume is not None
    assert result.volume.unit == unit
    assert result.volume.size == pytest.approx(size)


@pytest.mark.parametrize(
    ("raw", "reason_code"),
    [
        (10, "symsignals_volume_missing_unit"),
        ("10", "symsignals_volume_missing_unit"),
        (-1, "symsignals_volume_negative"),
        (math.inf, "symsignals_volume_nonfinite"),
        (math.nan, "symsignals_volume_nonfinite"),
        (None, "symsignals_volume_invalid_type"),
        (True, "symsignals_volume_invalid_type"),
        ("1T", "symsignals_volume_malformed"),
        ("ten M", "symsignals_volume_malformed"),
        ("-2M", "symsignals_volume_malformed"),
        ("1e6", "symsignals_volume_malformed"),
    ],
)
def test_parse_external_volume_rejects_ambiguous_or_invalid_values(
    raw: Any,
    reason_code: str,
) -> None:
    result = parse_external_volume(raw)

    assert result.volume is None
    assert result.reason_code == reason_code
