"""Pure, deterministic accumulation-dip strategy shared by live and replay.

This module owns observations and candidate calculations, never exchange orders
or execution consumption. Confirmed fills remain the only source of the guard.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID

from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.data_timeframes import (
    align_timestamp_to_bucket_floor,
    timeframe_bucket_origin_milliseconds,
    timeframe_to_milliseconds,
)

CAPABILITY = "accumulation/v1"
CATALOG_PREFIX = "accumulation_variant_"
BUILTIN_ACCUMULATION_SLUG = CATALOG_PREFIX + "dip_atr"
IMPLEMENTATION = "accumulation_dip_v1"
PRIORITY_PROTOCOL = "peak_atr_v1"
SUPPORTED_TIMEFRAMES = frozenset({"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"})


def _decimal(value: str, *, positive: bool = True) -> Decimal:
    return Decimal(canonical_decimal(value, positive=positive))


def _timestamp(value: Any) -> int:
    if type(value) is not int or not 0 <= value < 2**63:
        raise AccumulationStateError("Invalid candle timestamp.")
    return value


@dataclass(frozen=True)
class AccumulationParameters:
    """Immutable experimental strategy parameters, expressed in explicit units."""

    timeframe: str = "1h"
    peak_length: int = 168
    atr_length: int = 14
    entry_atr: str = "1.5"
    spacing_atr: str = "1"
    recovery_atr: str = "1"
    min_fraction: str = "0.02"
    slope: str = "0.03"
    max_fraction: str = "0.20"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.timeframe, str)
            or self.timeframe not in SUPPORTED_TIMEFRAMES
        ):
            raise AccumulationStateError("Unsupported accumulation timeframe.")
        if type(self.peak_length) is not int or not 2 <= self.peak_length <= 1000:
            raise AccumulationStateError(
                "peak_length must be an integer from 2 to 1000."
            )
        if type(self.atr_length) is not int or not 2 <= self.atr_length <= 100:
            raise AccumulationStateError("atr_length must be an integer from 2 to 100.")
        for name in (
            "entry_atr",
            "spacing_atr",
            "recovery_atr",
            "min_fraction",
            "slope",
            "max_fraction",
        ):
            _decimal(getattr(self, name))
        if not _decimal(self.min_fraction) <= _decimal(self.max_fraction) <= 1:
            raise AccumulationStateError("Fractions must satisfy 0 < min <= max <= 1.")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AccumulationParameters:
        """Require a complete versioned parameter set; reject implicit new defaults."""
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise AccumulationStateError(
                "Incomplete or unknown accumulation parameters."
            )
        return cls(**value)

    @property
    def history_length(self) -> int:
        """Return K true-range samples plus their preceding close."""
        return max(252, self.peak_length, 18 * self.atr_length) + 1

    @property
    def interval_ms(self) -> int:
        """Return the supported fixed candle interval."""
        return timeframe_to_milliseconds(self.timeframe)

    def latest_close(self, now_ms: int) -> int:
        """Use candle close timestamps, including Monday alignment for weekly bars."""
        return align_timestamp_to_bucket_floor(
            _timestamp(now_ms),
            self.interval_ms,
            timeframe_bucket_origin_milliseconds(self.timeframe),
        )


def build_accumulation_strategy_document(
    parameters: AccumulationParameters | None = None,
) -> dict[str, Any]:
    """Build the immutable accumulation payload used by built-ins and variants."""
    return {
        "schema_version": 1,
        "capability": CAPABILITY,
        "implementation": IMPLEMENTATION,
        "priority_protocol": PRIORITY_PROTOCOL,
        "parameters": asdict(parameters or AccumulationParameters()),
    }


def parse_accumulation_strategy_document(
    value: dict[str, Any],
) -> AccumulationParameters:
    """Reject ordinary DCA graphs and unrecognized accumulation implementations."""
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "capability",
        "implementation",
        "priority_protocol",
        "parameters",
    }:
        raise AccumulationStateError(
            "Strategy does not declare an accumulation contract."
        )
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["capability"] != CAPABILITY
        or value["implementation"] != IMPLEMENTATION
        or value["priority_protocol"] != PRIORITY_PROTOCOL
    ):
        raise AccumulationStateError("Unsupported accumulation strategy contract.")
    return AccumulationParameters.from_dict(value["parameters"])


@dataclass(frozen=True)
class AccumulationCandle:
    """One complete spot OHLC bar identified by its closing timestamp."""

    close_ms: int
    open: str
    high: str
    low: str
    close: str

    def __post_init__(self) -> None:
        _timestamp(self.close_ms)
        opening, high, low, close = (
            _decimal(getattr(self, name)) for name in ("open", "high", "low", "close")
        )
        if not low <= min(opening, close) <= max(opening, close) <= high:
            raise AccumulationStateError("Inconsistent OHLC candle.")


@dataclass(frozen=True)
class AccumulationMarket:
    """Completed-candle observations derived from a bounded history window."""

    close_ms: int
    close: str
    previous_close: str
    peak: str
    atr: str
    severity: str


def calculate_accumulation_market(
    candles: Sequence[AccumulationCandle],
    parameters: AccumulationParameters,
    *,
    close_ms: int,
) -> AccumulationMarket:
    """Calculate prior-high peak and exactly seeded Wilder ATR without lookahead."""
    _timestamp(close_ms)
    if len(candles) != parameters.history_length:
        raise AccumulationStateError("WAIT_DATA: exact bounded warmup window required.")
    interval = parameters.interval_ms
    origin = timeframe_bucket_origin_milliseconds(parameters.timeframe)
    for index, candle in enumerate(candles):
        expected = close_ms - (len(candles) - index - 1) * interval
        if candle.close_ms != expected or (candle.close_ms - origin) % interval:
            raise AccumulationStateError(
                "WAIT_DATA: missing, unordered or unaligned candle."
            )
    with localcontext() as context:
        context.prec = 50
        ranges = [
            max(
                _decimal(current.high) - _decimal(current.low),
                abs(_decimal(current.high) - _decimal(previous.close)),
                abs(_decimal(current.low) - _decimal(previous.close)),
            )
            for previous, current in zip(candles, candles[1:])
        ]
        length = parameters.atr_length
        atr = sum(ranges[:length], Decimal(0)) / length
        for value in ranges[length:]:
            atr = ((length - 1) * atr + value) / length
        if atr <= 0:
            raise AccumulationStateError("WAIT_DATA: ATR must be positive.")
        peak = max(
            _decimal(candle.high)
            for candle in candles[-parameters.peak_length - 1 : -1]
        )
        close = _decimal(candles[-1].close)
        severity = max(Decimal(0), (peak - close) / atr)
        return AccumulationMarket(
            close_ms, str(close), candles[-2].close, str(peak), str(atr), str(severity)
        )


def canonical_accumulation_priority(
    candles: Sequence[AccumulationCandle], *, close_ms: int
) -> str:
    """Use the same fixed hourly 168/14/252 severity for every candidate."""
    return calculate_accumulation_market(
        candles, AccumulationParameters(), close_ms=close_ms
    ).severity


@dataclass(frozen=True)
class AccumulationGuard:
    """Frozen consumed signal anchor supplied only by confirmed-fill accounting."""

    opportunity_id: str
    signal_close_ms: int
    signal_price: str
    signal_atr: str
    strategy_version_id: int
    consumption_revision: int

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AccumulationGuard:
        """Fail closed on missing or unversioned execution history."""
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise AccumulationStateError("Incomplete execution guard.")
        UUID(value["opportunity_id"])
        _timestamp(value["signal_close_ms"])
        _decimal(value["signal_price"])
        _decimal(value["signal_atr"])
        for key in ("strategy_version_id", "consumption_revision"):
            if type(value[key]) is not int or value[key] < 1:
                raise AccumulationStateError("Invalid execution guard revision.")
        return cls(**value)


@dataclass(frozen=True)
class AccumulationObservations:
    """Bounded recovery state, separate from execution consumption."""

    last_close_ms: int
    consumption_revision: int
    high_close: str | None = None
    atr_at_high: str | None = None
    recovery_ready: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AccumulationObservations:
        """Validate saved strategy-private state instead of silently bootstrapping."""
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise AccumulationStateError("Invalid accumulation observations.")
        _timestamp(value["last_close_ms"])
        if (
            type(value["consumption_revision"]) is not int
            or value["consumption_revision"] < 0
            or type(value["recovery_ready"]) is not bool
        ):
            raise AccumulationStateError("Invalid recovery observation identity.")
        if (value["high_close"] is None) != (value["atr_at_high"] is None):
            raise AccumulationStateError("Incomplete recovery high.")
        if value["high_close"] is not None:
            _decimal(value["high_close"])
            _decimal(value["atr_at_high"])
        elif value["recovery_ready"]:
            raise AccumulationStateError("Recovery cannot be ready without a high.")
        return cls(**value)


def advance_accumulation_observations(
    state: AccumulationObservations,
    market: AccumulationMarket,
    guard: AccumulationGuard | None,
    parameters: AccumulationParameters,
) -> AccumulationObservations:
    """Observe each later close, resetting recovery only on new consumption."""
    revision = guard.consumption_revision if guard else 0
    if state.consumption_revision > revision or market.close_ms < state.last_close_ms:
        raise AccumulationStateError("Observations or consumption moved backward.")
    if state.consumption_revision != revision:
        state = AccumulationObservations(state.last_close_ms, revision)
    if market.close_ms == state.last_close_ms:
        return state
    state = replace(state, last_close_ms=market.close_ms)
    if guard is None or market.close_ms <= guard.signal_close_ms:
        return state
    if state.high_close is None or _decimal(market.close) > _decimal(state.high_close):
        state = replace(state, high_close=market.close, atr_at_high=market.atr)
    with localcontext() as context:
        context.prec = 50
        threshold = _decimal(guard.signal_price) + _decimal(
            parameters.recovery_atr
        ) * _decimal(guard.signal_atr)
        return replace(
            state,
            recovery_ready=state.recovery_ready
            or _decimal(state.high_close) >= threshold,
        )


def accumulation_signal_reason(
    market: AccumulationMarket,
    state: AccumulationObservations,
    guard: AccumulationGuard | None,
    parameters: AccumulationParameters,
) -> str:
    """Require a fresh decline and either first entry or a genuine market rearm."""
    if _decimal(market.close) >= _decimal(market.previous_close):
        return "WAIT_DECLINE"
    if _decimal(market.severity, positive=False) < _decimal(parameters.entry_atr):
        return "WAIT_DEPTH"
    if guard is None:
        return "BUY_FIRST_DIP"
    if market.close_ms <= guard.signal_close_ms:
        return "WAIT_REARM"
    with localcontext() as context:
        context.prec = 50
        if _decimal(market.close) <= _decimal(guard.signal_price) - _decimal(
            parameters.spacing_atr
        ) * _decimal(guard.signal_atr):
            return "BUY_FURTHER_DECLINE"
        if state.recovery_ready and _decimal(market.close) <= _decimal(
            state.high_close
        ) - _decimal(parameters.spacing_atr) * _decimal(state.atr_at_high):
            return "BUY_FRESH_CORRECTION"
    return "WAIT_REARM"


def accumulation_requested_quote(
    severity: str, usable_quote: str, parameters: AccumulationParameters
) -> tuple[str, str]:
    """Return fraction and principal, never topping up or clipping to a minimum."""
    with localcontext() as context:
        context.prec = 50
        depth, usable = (
            _decimal(severity, positive=False),
            _decimal(usable_quote, positive=False),
        )
        if depth < _decimal(parameters.entry_atr):
            raise AccumulationStateError("Sizing requires an eligible dip.")
        fraction = min(
            _decimal(parameters.max_fraction),
            _decimal(parameters.min_fraction)
            + _decimal(parameters.slope) * (depth - _decimal(parameters.entry_atr)),
        )
        return str(fraction), canonical_decimal(str(fraction * usable))


def rebuild_accumulation_observations(
    candles: Sequence[AccumulationCandle],
    parameters: AccumulationParameters,
    guard: AccumulationGuard | None,
    *,
    baseline_close_ms: int,
) -> AccumulationObservations:
    """Warm up bounded post-consumption observations without emitting purchases.

    At most K completed observations plus their K-bar ATR warmup are accepted.
    Historical opportunities are deliberately not reconstructed by this helper.
    """
    length = parameters.history_length
    if (
        not length <= len(candles) <= 2 * length - 1
        or candles[-1].close_ms != baseline_close_ms
    ):
        raise AccumulationStateError("WAIT_DATA: invalid bounded rebase window.")
    state = AccumulationObservations(
        candles[length - 1].close_ms - parameters.interval_ms,
        guard.consumption_revision if guard else 0,
    )
    for end in range(length, len(candles) + 1):
        market = calculate_accumulation_market(
            candles[end - length : end], parameters, close_ms=candles[end - 1].close_ms
        )
        state = advance_accumulation_observations(state, market, guard, parameters)
    return state
