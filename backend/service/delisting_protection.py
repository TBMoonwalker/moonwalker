"""Optional exchange-aware protection against opening exposure before delisting."""

from __future__ import annotations

import asyncio
import copy
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

    async def fetch(self, exchange: Exchange, config: dict[str, Any]) -> list[Any]:
        """Return raw schedule entries from the exchange."""


class BinanceSpotDelistingProvider:
    """Fetch Binance's authenticated Spot delisting schedule."""

    source = "binance_spot_schedule"

    async def fetch(self, exchange: Exchange, config: dict[str, Any]) -> list[Any]:
        """Return Binance Spot delisting schedule entries."""
        return await exchange.fetch_spot_delist_schedule(config)


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
            events: dict[str, DelistingEvent] = {}
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
                    market = self._markets_by_id.get(market_id)
                    symbol = (
                        str(market.get("symbol"))
                        if isinstance(market, dict) and market.get("symbol")
                        else None
                    )
                    events[market_id] = DelistingEvent(
                        exchange_id=str(config.get("exchange") or ""),
                        market_id=market_id,
                        symbol=symbol,
                        delist_time_ms=delist_time_ms,
                        source=provider.source,
                    )
            self._events_by_market_id = events
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
        if (
            provider is not None
            and not bool(config.get("dry_run", True))
            and not self._schedule_verified
        ):
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
            degraded=bool(self._degraded_reason) or market.get("active") is None,
        )

    def enrich_open_trades(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Annotate open trades affected by a known schedule or inactive market."""
        enriched: list[dict[str, Any]] = []
        enabled = bool(self.config.get("delisting_protection_enabled", False))
        for source_row in rows:
            row = dict(source_row)
            symbol = str(row.get("symbol") or "")
            event = self._event_for_symbol(symbol) if enabled else None
            market = self._market_for_symbol(symbol) if enabled else None
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
                "scheduled_symbols": sorted(self._events_by_market_id),
            }
        )
