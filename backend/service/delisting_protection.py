"""Optional exchange-aware protection against opening exposure before delisting."""

from __future__ import annotations

import asyncio
import copy
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import ccxt.async_support as ccxt
import helper
from service.config import Config
from service.exchange import Exchange
from service.monitoring import MonitoringService
from service.trades import Trades

logging = helper.LoggerFactory.get_logger(
    "logs/delisting_protection.log",
    "delisting_protection",
)

MARKET_REFRESH_SECONDS = 300.0
MARKET_MAX_STALE_SECONDS = 600.0
SCHEDULE_REFRESH_SECONDS = 1800.0
SCHEDULE_MAX_STALE_SECONDS = 3600.0
IDLE_LOOP_SECONDS = 60.0

# Bybit publishes spot delistings through a public, unauthenticated
# announcement feed. Entries are advisory, so a transient feed failure must
# never freeze trading; only recent announcements are considered, and stale
# entries are dropped on refresh.
BYBIT_ANNOUNCEMENT_LOOKBACK_SECONDS = 24 * 3600
BYBIT_ANNOUNCEMENT_MAX_FUTURE_YEAR = 2100

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_DATE_PATTERN = re.compile(
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"[a-z]*)\D+(\d{1,2})\D+(\d{4})",
    re.IGNORECASE,
)
_BASE_ASSET_PATTERN = re.compile(r"[A-Z][A-Z0-9&]{1,8}")
_BASE_ASSET_STOPWORDS = frozenset(
    {
        "USDT",
        "USDC",
        "BUSD",
        "TUSD",
        "DAI",
        "USD",
        "EUR",
        "BYT",
        "BTC",
        "ETH",
        "TRADING",
        "PAIR",
        "PAIRS",
        "MARKET",
        "MARKETS",
        "LIST",
        "LISTING",
        "DELIST",
        "DELISTING",
        "DELISTS",
        "ANNOUNCEMENT",
        "ANNOUNCEMENTS",
        "CONTRACT",
        "SPOT",
    }
)
_DERIVATIVES_INDICATORS = (
    "perpetual",
    "future",
    "inverse",
    "option",
    "derivat",
    "delivery",
    "swap",
)


@dataclass(frozen=True)
class DelistingEvent:
    """One normalized exchange delisting event."""

    exchange_id: str
    market_id: str
    symbol: str | None
    delist_time_ms: int
    source: str

    @property
    def delist_at(self) -> str:
        """Return the delisting timestamp as an ISO-8601 UTC value."""
        return datetime.fromtimestamp(
            self.delist_time_ms / 1000,
            tz=timezone.utc,
        ).isoformat()


@dataclass(frozen=True)
class DelistingDecision:
    """Explain whether delisting protection allows one buy."""

    allowed: bool
    reason_code: str | None = None
    message: str | None = None
    source: str | None = None
    delist_at: str | None = None
    degraded: bool = False


class DelistingProvider(Protocol):
    """Protocol implemented by exchange-specific schedule providers."""

    source: str

    fail_closed: bool

    async def fetch(self, exchange: Exchange, config: dict[str, Any]) -> list[Any]:
        """Return raw schedule entries from the exchange."""


class BinanceSpotDelistingProvider:
    """Fetch Binance's authenticated Spot delisting schedule."""

    source = "binance_spot_schedule"
    fail_closed = True

    async def fetch(self, exchange: Exchange, config: dict[str, Any]) -> list[Any]:
        """Return Binance Spot delisting schedule entries."""
        return await exchange.fetch_spot_delist_schedule(config)


class BybitDelistingProvider:
    """Fetch Bybit's public, advisory spot delisting announcements.

    Unlike Binance, Bybit exposes no authenticated delisting schedule; spot
    delistings are published through a public announcement feed. Because the
    schedule is advisory, a transient feed failure must not freeze trading.
    """

    source = "bybit_announcement_schedule"
    fail_closed = False

    async def fetch(self, exchange: Exchange, config: dict[str, Any]) -> list[Any]:
        """Return Bybit public spot delisting announcements."""
        return await exchange.fetch_bybit_delisting_schedule(config)


def _is_fail_closed(provider: DelistingProvider) -> bool:
    """Return whether an unverified schedule must block new buys."""
    return bool(getattr(provider, "fail_closed", True))


def _announcement_text(announcement: dict[str, Any]) -> str:
    """Return the joined title and description of one announcement."""
    parts: list[str] = []
    for key in ("title", "description"):
        value = announcement.get(key)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(part for part in parts if part)


def _announcement_tags(announcement: dict[str, Any]) -> list[str]:
    """Return normalized tag strings attached to an announcement."""
    raw_tags = announcement.get("tags")
    if not isinstance(raw_tags, list):
        return []
    result: list[str] = []
    for tag in raw_tags:
        if isinstance(tag, str):
            result.append(tag)
        elif isinstance(tag, dict):
            key = tag.get("key")
            if isinstance(key, str):
                result.append(key)
    return result


def _announcement_is_derivatives_only(
    announcement: dict[str, Any],
) -> bool:
    """Return whether an announcement concerns a derivatives-only market."""
    haystack = _announcement_text(announcement)
    for tag in _announcement_tags(announcement):
        haystack = f"{haystack} {tag}"
    haystack = haystack.lower()
    return any(indicator in haystack for indicator in _DERIVATIVES_INDICATORS)


def _parse_text_date_ms(text: str) -> int | None:
    """Return a 'Mon D, YYYY' date parsed from text as UTC milliseconds."""
    match = _DATE_PATTERN.search(text)
    if match is None:
        return None
    month_number = _MONTHS.get(match.group(1).lower()[:3])
    if month_number is None:
        return None
    try:
        day = int(match.group(2))
        year = int(match.group(3))
        if year >= BYBIT_ANNOUNCEMENT_MAX_FUTURE_YEAR:
            return None
        parsed = datetime(year, month_number, day, tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)


def _parse_announcement_date_ms(
    announcement: dict[str, Any],
) -> int | None:
    """Return the delist timestamp for an announcement, if resolvable."""
    raw_timestamp = announcement.get("dateTimestamp")
    try:
        timestamp_ms = int(raw_timestamp)
    except (TypeError, ValueError):
        timestamp_ms = 0
    if timestamp_ms > 0:
        try:
            parsed_year = datetime.fromtimestamp(
                timestamp_ms / 1000,
                tz=timezone.utc,
            ).year
        except (OverflowError, OSError, ValueError):
            parsed_year = 0
        if 0 < parsed_year < BYBIT_ANNOUNCEMENT_MAX_FUTURE_YEAR:
            return timestamp_ms
    return _parse_text_date_ms(_announcement_text(announcement))


def _announcement_delist_time(
    announcement: dict[str, Any],
    *,
    now_ms: int,
) -> int | None:
    """Return a non-stale delist timestamp, skipping unavailable entries."""
    delist_ms = _parse_announcement_date_ms(announcement)
    if delist_ms is None:
        return None
    if delist_ms < now_ms - BYBIT_ANNOUNCEMENT_LOOKBACK_SECONDS * 1000:
        return None
    return delist_ms


def _announcement_base_assets(text: str) -> list[str]:
    """Return candidate base asset tokens from announcement text."""
    candidates: list[str] = []
    seen: set[str] = set()
    for match in _BASE_ASSET_PATTERN.finditer(text):
        token = match.group(0)
        if token in seen or token in _BASE_ASSET_STOPWORDS:
            continue
        seen.add(token)
        candidates.append(token)
    return candidates


def _market_base(market: dict[str, Any]) -> str:
    """Return the normalized base asset of a CCXT market symbol."""
    symbol = market.get("symbol")
    if not isinstance(symbol, str) or "/" not in symbol:
        return ""
    base, _, _ = symbol.partition("/")
    return _normalize_symbol(base)


def _is_spot_market(market: dict[str, Any]) -> bool:
    """Return whether a market belongs to the spot product."""
    market_type = market.get("type")
    return market_type in (None, "", "spot")


def _parse_binance_spot_schedule(
    raw_entries: list[Any],
    config: dict[str, Any],
    markets_by_id: dict[str, dict[str, Any]],
) -> dict[str, DelistingEvent]:
    """Normalize Binance Spot delisting schedule entries into events."""
    events: dict[str, DelistingEvent] = {}
    exchange_id = str(config.get("exchange") or "").strip().lower()
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        try:
            delist_time_ms = int(entry.get("delistTime"))
        except (TypeError, ValueError):
            continue
        if delist_time_ms <= 0:
            continue
        symbols = entry.get("symbols")
        if not isinstance(symbols, list):
            continue
        for raw_symbol in symbols:
            market_id = _normalize_market_id(raw_symbol)
            if not market_id:
                continue
            market = markets_by_id.get(market_id)
            symbol = (
                str(market.get("symbol"))
                if isinstance(market, dict) and market.get("symbol")
                else None
            )
            events[market_id] = DelistingEvent(
                exchange_id=exchange_id,
                market_id=market_id,
                symbol=symbol,
                delist_time_ms=delist_time_ms,
                source="binance_spot_schedule",
            )
    return events


def _parse_bybit_announcements(
    raw_entries: list[Any],
    config: dict[str, Any],
    markets_by_id: dict[str, dict[str, Any]],
    *,
    now_ms: int,
) -> dict[str, DelistingEvent]:
    """Normalize Bybit delisting announcements into spot events."""
    events: dict[str, DelistingEvent] = {}
    exchange_id = str(config.get("exchange") or "").strip().lower()
    markets_by_base: dict[str, list[dict[str, Any]]] = {}
    for market in markets_by_id.values():
        if not isinstance(market, dict) or not _is_spot_market(market):
            continue
        base = _market_base(market)
        if base:
            markets_by_base.setdefault(base, []).append(market)
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        if _announcement_is_derivatives_only(entry):
            continue
        delist_ms = _announcement_delist_time(entry, now_ms=now_ms)
        if delist_ms is None:
            continue
        text = _announcement_text(entry)
        for base in _announcement_base_assets(text):
            for market in markets_by_base.get(base, []):
                market_id = _normalize_market_id(market.get("id"))
                if not market_id:
                    continue
                symbol = (
                    str(market.get("symbol"))
                    if isinstance(market, dict) and market.get("symbol")
                    else None
                )
                events[market_id] = DelistingEvent(
                    exchange_id=exchange_id,
                    market_id=market_id,
                    symbol=symbol,
                    delist_time_ms=delist_ms,
                    source="bybit_announcement_schedule",
                )
    return events


def _normalize_schedule(
    provider: DelistingProvider,
    raw_entries: list[Any],
    config: dict[str, Any],
    markets_by_id: dict[str, dict[str, Any]],
    *,
    now_ms: int,
) -> dict[str, DelistingEvent]:
    """Dispatch raw provider entries to the matching schedule normalizer."""
    if provider.source == "bybit_announcement_schedule":
        return _parse_bybit_announcements(
            raw_entries,
            config,
            markets_by_id,
            now_ms=now_ms,
        )
    return _parse_binance_spot_schedule(raw_entries, config, markets_by_id)


def _normalize_symbol(value: Any) -> str:
    """Return a case-insensitive CCXT symbol lookup key."""
    return str(value or "").strip().upper()


def _normalize_market_id(value: Any) -> str:
    """Return a normalized raw exchange market identifier."""
    return "".join(
        character for character in _normalize_symbol(value) if character.isalnum()
    )


def _provider_for(config: dict[str, Any]) -> DelistingProvider | None:
    """Return the dedicated provider for the configured exchange and market."""
    exchange_id = str(config.get("exchange") or "").strip().lower()
    market = str(config.get("market") or "spot").strip().lower()
    if exchange_id == "binance" and market == "spot":
        return BinanceSpotDelistingProvider()
    if exchange_id in ("bybit", "bybiteu") and market == "spot":
        return BybitDelistingProvider()
    return None


class DelistingProtectionService:
    """Maintain delisting state and guard every executable buy path."""

    _instance: DelistingProtectionService | None = None

    def __init__(self) -> None:
        """Initialize collaborators and an empty runtime snapshot."""
        self.config: dict[str, Any] = {}
        self.exchange = Exchange()
        self.trades = Trades()
        self.monitoring = MonitoringService()
        self._refresh_lock = asyncio.Lock()
        self._refresh_requested = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._fingerprint: tuple[Any, ...] | None = None
        self._markets: dict[str, dict[str, Any]] = {}
        self._markets_by_id: dict[str, dict[str, Any]] = {}
        self._events_by_market_id: dict[str, DelistingEvent] = {}
        self._market_checked_at = 0.0
        self._schedule_checked_at = 0.0
        self._market_verified = False
        self._schedule_verified = False
        self._degraded_reason: str | None = None
        self._notified_events: set[tuple[str, str, str]] = set()

    @classmethod
    def shared(cls) -> "DelistingProtectionService":
        """Return the process-wide service without requiring async initialization."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    async def instance(cls) -> "DelistingProtectionService":
        """Return the initialized process-wide service."""
        instance = cls.shared()
        if not instance.config:
            await instance.init()
        return instance

    async def init(self) -> None:
        """Subscribe to runtime configuration changes."""
        config = await Config.instance()
        config.subscribe(self.on_config_change)
        self.on_config_change(config.snapshot())

    async def start(self) -> None:
        """Start periodic refresh and open-trade warning checks."""
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def shutdown(self) -> None:
        """Stop refresh work and close the dedicated exchange client."""
        self._running = False
        self._refresh_requested.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self.exchange.close()

    def on_config_change(self, config: dict[str, Any]) -> None:
        """Capture configuration and request an immediate eligibility refresh."""
        previous_fingerprint = self._build_fingerprint(self.config)
        self.config = dict(config)
        current_fingerprint = self._build_fingerprint(self.config)
        if previous_fingerprint != current_fingerprint:
            self._refresh_requested.set()
            if not bool(self.config.get("delisting_protection_enabled", False)):
                self._reset_snapshot()

    async def _run_loop(self) -> None:
        """Refresh protection state while keeping transient failures isolated."""
        while self._running:
            # Clear before refreshing so a config change that arrives during the
            # refresh remains set and triggers another pass immediately.
            self._refresh_requested.clear()
            try:
                if bool(self.config.get("delisting_protection_enabled", False)):
                    await self.refresh(self.config)
            except Exception as exc:  # noqa: BLE001 - runtime guard must stay alive.
                logging.error(
                    "Delisting protection refresh failed: %s",
                    exc,
                    exc_info=True,
                )

            try:
                await asyncio.wait_for(
                    self._refresh_requested.wait(),
                    timeout=IDLE_LOOP_SECONDS,
                )
            except asyncio.TimeoutError:
                pass

    @staticmethod
    def _build_fingerprint(config: dict[str, Any]) -> tuple[Any, ...]:
        """Return fields that identify one exchange protection context."""
        return (
            bool(config.get("delisting_protection_enabled", False)),
            str(config.get("exchange") or "").strip().lower(),
            str(config.get("market") or "spot").strip().lower(),
            bool(config.get("dry_run", True)),
            str(config.get("exchange_hostname") or "").strip().lower(),
            str(config.get("key") or "").strip(),
            str(config.get("secret") or "").strip(),
            bool(
                config.get(
                    "delisting_schedule_use_trading_credentials",
                    False,
                )
            ),
            str(config.get("delisting_schedule_api_key") or "").strip(),
            str(config.get("delisting_schedule_api_secret") or "").strip(),
        )

    def _reset_snapshot(self) -> None:
        """Clear all exchange-derived state."""
        self._fingerprint = None
        self._markets = {}
        self._markets_by_id = {}
        self._events_by_market_id = {}
        self._market_checked_at = 0.0
        self._schedule_checked_at = 0.0
        self._market_verified = False
        self._schedule_verified = False
        self._degraded_reason = None

    def _snapshot_matches(self, config: dict[str, Any]) -> bool:
        """Return whether cached data belongs to the supplied configuration."""
        return self._fingerprint == self._build_fingerprint(config)

    async def ensure_fresh(self, config: dict[str, Any]) -> None:
        """Refresh stale market or schedule information before a buy."""
        if not bool(config.get("delisting_protection_enabled", False)):
            return
        now = time.monotonic()
        provider = _provider_for(config)
        market_stale = (
            not self._snapshot_matches(config)
            or now - self._market_checked_at >= MARKET_REFRESH_SECONDS
        )
        schedule_stale = provider is not None and (
            not self._snapshot_matches(config)
            or now - self._schedule_checked_at >= SCHEDULE_REFRESH_SECONDS
        )
        if market_stale or schedule_stale:
            await self.refresh(config)

    async def refresh(self, config: dict[str, Any]) -> None:
        """Refresh CCXT market status and any dedicated delisting schedule."""
        if not bool(config.get("delisting_protection_enabled", False)):
            self._reset_snapshot()
            return

        async with self._refresh_lock:
            fingerprint = self._build_fingerprint(config)
            if self._fingerprint != fingerprint:
                self._reset_snapshot()
                self._fingerprint = fingerprint

            now = time.monotonic()
            provider = _provider_for(config)
            degraded_reasons: list[str] = []

            if (
                not self._market_verified
                or now - self._market_checked_at >= MARKET_REFRESH_SECONDS
            ):
                await self._refresh_markets(config, now, degraded_reasons)

            if provider is not None and (
                not self._schedule_verified
                or now - self._schedule_checked_at >= SCHEDULE_REFRESH_SECONDS
            ):
                await self._refresh_schedule(
                    provider,
                    config,
                    now,
                    degraded_reasons,
                )
            elif provider is None:
                self._schedule_verified = False
                self._events_by_market_id = {}

            self._degraded_reason = "; ".join(degraded_reasons) or None

        await self._notify_affected_open_trades(config)

    async def _refresh_markets(
        self,
        config: dict[str, Any],
        now: float,
        degraded_reasons: list[str],
    ) -> None:
        """Refresh and index CCXT market metadata."""
        previous_age = now - self._market_checked_at
        try:
            markets = await self.exchange.fetch_market_metadata(
                config,
                force_refresh=True,
            )
            by_symbol: dict[str, dict[str, Any]] = {}
            by_id: dict[str, dict[str, Any]] = {}
            for market in markets:
                symbol_key = _normalize_symbol(market.get("symbol"))
                market_id = _normalize_market_id(market.get("id"))
                if symbol_key:
                    by_symbol[symbol_key] = market
                if market_id:
                    by_id[market_id] = market
            self._markets = by_symbol
            self._markets_by_id = by_id
            self._market_checked_at = now
            self._market_verified = True
        except (
            ccxt.BaseError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            if self._market_verified and previous_age <= MARKET_MAX_STALE_SECONDS:
                degraded_reasons.append(f"market refresh failed; using cache: {exc}")
            else:
                self._market_verified = False
                self._markets = {}
                self._markets_by_id = {}
                degraded_reasons.append(f"market refresh unavailable: {exc}")
        finally:
            await self.exchange.close()

    async def _refresh_schedule(
        self,
        provider: DelistingProvider,
        config: dict[str, Any],
        now: float,
        degraded_reasons: list[str],
    ) -> None:
        """Refresh and normalize an exchange-specific delisting schedule."""
        previous_age = now - self._schedule_checked_at
        try:
            raw_entries = await provider.fetch(self.exchange, config)
            self._events_by_market_id = _normalize_schedule(
                provider,
                raw_entries,
                config,
                self._markets_by_id,
                now_ms=int(time.time() * 1000),
            )
            self._schedule_checked_at = now
            self._schedule_verified = True
        except (
            ccxt.BaseError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            if self._schedule_verified and previous_age <= SCHEDULE_MAX_STALE_SECONDS:
                degraded_reasons.append(f"schedule refresh failed; using cache: {exc}")
            else:
                self._schedule_verified = False
                if previous_age > SCHEDULE_MAX_STALE_SECONDS:
                    self._events_by_market_id = {}
                degraded_reasons.append(f"schedule refresh unavailable: {exc}")
        finally:
            await self.exchange.close()

    def _market_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        """Resolve cached market metadata from a CCXT symbol or exchange ID."""
        normalized_symbol = _normalize_symbol(symbol)
        market = self._markets.get(normalized_symbol)
        if market is not None:
            return market
        return self._markets_by_id.get(_normalize_market_id(symbol))

    def _event_for_symbol(self, symbol: str) -> DelistingEvent | None:
        """Resolve a scheduled event from a CCXT symbol or exchange ID."""
        market = self._market_for_symbol(symbol)
        if market is not None:
            market_id = _normalize_market_id(market.get("id"))
            if market_id:
                return self._events_by_market_id.get(market_id)
        return self._events_by_market_id.get(_normalize_market_id(symbol))

    async def evaluate_buy(
        self,
        symbol: str,
        config: dict[str, Any],
    ) -> DelistingDecision:
        """Return whether delisting protection permits a buy-like action."""
        if not bool(config.get("delisting_protection_enabled", False)):
            return DelistingDecision(allowed=True)

        await self.ensure_fresh(config)
        event = self._event_for_symbol(symbol)
        if event is not None:
            return DelistingDecision(
                allowed=False,
                reason_code="blocked_scheduled_delisting",
                message=(
                    f"{symbol} is scheduled for delisting at {event.delist_at}. "
                    "New exposure is blocked while existing exits remain available."
                ),
                source=event.source,
                delist_at=event.delist_at,
                degraded=bool(self._degraded_reason),
            )

        provider = _provider_for(config)
        schedule_unverified = provider is not None and not self._schedule_verified
        if schedule_unverified and _is_fail_closed(provider):
            return DelistingDecision(
                allowed=False,
                reason_code="blocked_delisting_check_unavailable",
                message=(
                    f"Moonwalker could not verify the delisting schedule for {symbol}."
                ),
                source=provider.source,
                degraded=True,
            )

        if not self._market_verified:
            return DelistingDecision(
                allowed=False,
                reason_code="blocked_delisting_check_unavailable",
                message=f"Moonwalker could not verify the market status for {symbol}.",
                source="ccxt_market_status",
                degraded=True,
            )

        market = self._market_for_symbol(symbol)
        if market is None:
            return DelistingDecision(
                allowed=False,
                reason_code="blocked_market_missing",
                message=f"{symbol} is missing from the refreshed exchange markets.",
                source="ccxt_market_status",
                degraded=bool(self._degraded_reason),
            )
        if market.get("active") is False:
            return DelistingDecision(
                allowed=False,
                reason_code="blocked_market_inactive",
                message=f"{symbol} is marked inactive by the exchange.",
                source="ccxt_market_status",
                degraded=bool(self._degraded_reason),
            )

        return DelistingDecision(
            allowed=True,
            source=(
                provider.source
                if provider is not None and self._schedule_verified
                else "ccxt_market_status"
            ),
            degraded=(
                bool(self._degraded_reason)
                or market.get("active") is None
                or schedule_unverified
            ),
        )

    def enrich_open_trades(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Annotate open trades affected by a known schedule or inactive market."""
        enriched: list[dict[str, Any]] = []
        enabled = bool(self.config.get("delisting_protection_enabled", False))
        provider = _provider_for(self.config) if enabled else None
        schedule_unavailable = (
            provider is not None
            and not self._schedule_verified
            and _is_fail_closed(provider)
        )
        for source_row in rows:
            row = dict(source_row)
            symbol = str(row.get("symbol") or "")
            event = self._event_for_symbol(symbol) if enabled else None
            market = self._market_for_symbol(symbol) if enabled else None
            if schedule_unavailable:
                row.update(
                    {
                        "delisting_check_unavailable": True,
                        "delisting_check_message": (
                            "The exchange delisting schedule could not be "
                            "verified. New buys are blocked while existing "
                            "exits remain enabled."
                        ),
                        "delisting_check_source": provider.source,
                    }
                )
            if event is not None:
                row.update(
                    {
                        "delisting_warning": True,
                        "delisting_at": event.delist_at,
                        "delisting_reason": "scheduled_delisting",
                        "delisting_source": event.source,
                    }
                )
            elif market is not None and market.get("active") is False:
                row.update(
                    {
                        "delisting_warning": True,
                        "delisting_at": None,
                        "delisting_reason": "market_inactive",
                        "delisting_source": "ccxt_market_status",
                    }
                )
            enriched.append(row)
        return enriched

    async def _notify_affected_open_trades(
        self,
        config: dict[str, Any],
    ) -> None:
        """Log and notify once for each affected open-trade event."""
        if not bool(config.get("delisting_protection_enabled", False)):
            return
        rows = self.enrich_open_trades(await self.trades.get_open_trades())
        provider = _provider_for(config)
        if (
            rows
            and provider is not None
            and not self._schedule_verified
            and _is_fail_closed(provider)
        ):
            notification_key = (
                str(config.get("exchange") or ""),
                "__schedule__",
                "unavailable",
            )
            if notification_key not in self._notified_events:
                self._notified_events.add(notification_key)
                logging.error(
                    "Delisting schedule is unavailable for exchange=%s. "
                    "All new buys are blocked; existing exits remain enabled. "
                    "reason=%s",
                    config.get("exchange"),
                    self._degraded_reason or "unknown",
                )
                await self.monitoring.notify_trade(
                    "risk.delisting_unavailable",
                    {
                        "symbol": "ALL OPEN TRADES",
                        "side": "risk",
                        "reason": "delisting_schedule_unavailable",
                        "source": provider.source,
                        "message": (
                            "Moonwalker cannot verify the production delisting "
                            "schedule. New buys are blocked. Existing sell and "
                            "take-profit orders remain enabled."
                        ),
                    },
                    config,
                )
        for row in rows:
            if not bool(row.get("delisting_warning")):
                continue
            symbol = str(row.get("symbol") or "")
            reason = str(row.get("delisting_reason") or "unknown")
            delist_at = str(row.get("delisting_at") or "")
            notification_key = (
                str(config.get("exchange") or ""),
                symbol,
                delist_at or reason,
            )
            if notification_key in self._notified_events:
                continue
            self._notified_events.add(notification_key)
            logging.warning(
                "Open trade %s is affected by delisting protection: "
                "reason=%s delist_at=%s source=%s. Buys are blocked; exits remain enabled.",
                symbol,
                reason,
                delist_at or "unknown",
                row.get("delisting_source"),
            )
            await self.monitoring.notify_trade(
                "risk.delisting",
                {
                    "symbol": symbol,
                    "side": "risk",
                    "reason": reason,
                    "delist_at": row.get("delisting_at"),
                    "source": row.get("delisting_source"),
                    "message": (
                        "New buys are blocked. Existing sell and take-profit "
                        "orders remain enabled."
                    ),
                },
                config,
            )

    def get_state(self) -> dict[str, Any]:
        """Return a defensive runtime status snapshot."""
        return copy.deepcopy(
            {
                "enabled": bool(self.config.get("delisting_protection_enabled", False)),
                "exchange": self.config.get("exchange"),
                "market_verified": self._market_verified,
                "schedule_verified": self._schedule_verified,
                "provider": (
                    _provider_for(self.config).source
                    if _provider_for(self.config) is not None
                    else "ccxt_market_status"
                ),
                "degraded_reason": self._degraded_reason,
                "schedule_credential_mode": (
                    "trading"
                    if self.config.get(
                        "delisting_schedule_use_trading_credentials",
                        False,
                    )
                    else "dedicated"
                ),
                "schedule_credentials_configured": bool(
                    (
                        self.config.get(
                            "delisting_schedule_use_trading_credentials",
                            False,
                        )
                        and self.config.get("key")
                        and self.config.get("secret")
                    )
                    or (
                        not self.config.get(
                            "delisting_schedule_use_trading_credentials",
                            False,
                        )
                        and self.config.get("delisting_schedule_api_key")
                        and self.config.get("delisting_schedule_api_secret")
                    )
                ),
                "scheduled_symbols": sorted(self._events_by_market_id),
            }
        )
