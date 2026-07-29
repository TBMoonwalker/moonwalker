"""Bounded-stale CoinMarketCap rank snapshots."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import helper
import httpx

logging = helper.LoggerFactory.get_logger(
    "logs/coin_market_cap.log",
    "coin_market_cap",
)

CMC_MAP_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/map"
SNAPSHOT_REFRESH_SECONDS = 24 * 60 * 60
SNAPSHOT_MAX_STALE_SECONDS = 7 * 24 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 10.0
REQUEST_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 0.25
_FINGERPRINT_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class MarketCapRankSnapshot:
    """One immutable symbol-to-rank provider snapshot."""

    api_key_fingerprint: str
    ranks: Mapping[str, int]
    fetched_at: float


@dataclass(frozen=True)
class MarketCapRankLookup:
    """Explain the rank data available for one admission decision."""

    rank: int | None
    available: bool
    reason_code: str
    snapshot_age_seconds: float | None = None
    stale: bool = False


class CoinMarketCapRankService:
    """Own one HTTP client and one bounded-stale market-rank snapshot."""

    def __init__(
        self,
        *,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize an inactive service.

        Args:
            client_factory: Factory used to create the lifespan-owned HTTP client.
            clock: Monotonic clock used to age snapshots.
        """
        self._client_factory = client_factory
        self._clock = clock
        self._client: httpx.AsyncClient | None = None
        self._snapshot: MarketCapRankSnapshot | None = None
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[MarketCapRankSnapshot | None] | None = None

    async def start(self) -> None:
        """Create the pooled HTTP client for the current application lifespan."""
        if self._client is None:
            self._client = self._client_factory(timeout=REQUEST_TIMEOUT_SECONDS)

    async def shutdown(self) -> None:
        """Stop background refresh work and close the pooled HTTP client."""
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_task.cancel()
            await asyncio.gather(self._refresh_task, return_exceptions=True)
        self._refresh_task = None

        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def lookup(self, api_key: str, symbol: str) -> MarketCapRankLookup:
        """Return a rank using fresh data or a bounded-stale snapshot."""
        normalized_key = api_key.strip()
        normalized_symbol = symbol.strip().upper()
        if not normalized_key:
            return MarketCapRankLookup(
                rank=None,
                available=False,
                reason_code="cmc_api_key_missing",
            )
        if not normalized_symbol:
            return MarketCapRankLookup(
                rank=None,
                available=False,
                reason_code="cmc_symbol_missing",
            )
        if self._client is None:
            return MarketCapRankLookup(
                rank=None,
                available=False,
                reason_code="cmc_service_not_started",
            )

        fingerprint = self._fingerprint(normalized_key)
        snapshot = self._matching_snapshot(fingerprint)
        if snapshot is not None:
            age = max(0.0, self._clock() - snapshot.fetched_at)
            if age <= SNAPSHOT_REFRESH_SECONDS:
                return self._lookup_snapshot(
                    snapshot,
                    normalized_symbol,
                    age=age,
                    stale=False,
                )
            if age <= SNAPSHOT_MAX_STALE_SECONDS:
                self._schedule_refresh(normalized_key, fingerprint)
                return self._lookup_snapshot(
                    snapshot,
                    normalized_symbol,
                    age=age,
                    stale=True,
                )

        snapshot = await self._refresh(normalized_key, fingerprint)
        if snapshot is None:
            return MarketCapRankLookup(
                rank=None,
                available=False,
                reason_code="cmc_snapshot_unavailable",
            )
        return self._lookup_snapshot(
            snapshot,
            normalized_symbol,
            age=max(0.0, self._clock() - snapshot.fetched_at),
            stale=False,
        )

    def _matching_snapshot(self, fingerprint: str) -> MarketCapRankSnapshot | None:
        """Return the snapshot only when it belongs to the current credential."""
        if (
            self._snapshot is not None
            and self._snapshot.api_key_fingerprint == fingerprint
        ):
            return self._snapshot
        return None

    @staticmethod
    def _fingerprint(api_key: str) -> str:
        """Return a process-local identity for snapshot ownership checks."""
        return hmac.new(
            _FINGERPRINT_KEY,
            api_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _lookup_snapshot(
        snapshot: MarketCapRankSnapshot,
        symbol: str,
        *,
        age: float,
        stale: bool,
    ) -> MarketCapRankLookup:
        """Resolve one symbol from a validated snapshot."""
        rank = snapshot.ranks.get(symbol)
        if rank is None:
            return MarketCapRankLookup(
                rank=None,
                available=False,
                reason_code="cmc_symbol_not_ranked",
                snapshot_age_seconds=age,
                stale=stale,
            )
        return MarketCapRankLookup(
            rank=rank,
            available=True,
            reason_code="cmc_snapshot_stale" if stale else "cmc_snapshot_fresh",
            snapshot_age_seconds=age,
            stale=stale,
        )

    def _schedule_refresh(self, api_key: str, fingerprint: str) -> None:
        """Start at most one stale-while-revalidate refresh."""
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(
            self._refresh(api_key, fingerprint, force=True),
            name="moonwalker:cmc-rank-refresh",
        )

    async def _refresh(
        self,
        api_key: str,
        fingerprint: str,
        *,
        force: bool = False,
    ) -> MarketCapRankSnapshot | None:
        """Refresh once under a single-flight lock."""
        async with self._refresh_lock:
            existing = self._matching_snapshot(fingerprint)
            if existing is not None and not force:
                age = max(0.0, self._clock() - existing.fetched_at)
                if age <= SNAPSHOT_REFRESH_SECONDS:
                    return existing

            if self._client is None:
                return None

            for attempt in range(1, REQUEST_ATTEMPTS + 1):
                try:
                    response = await self._client.get(
                        CMC_MAP_URL,
                        headers={"X-CMC_PRO_API_KEY": api_key},
                        params={"start": 1, "limit": 5000, "sort": "cmc_rank"},
                    )
                    response.raise_for_status()
                    ranks = self._parse_ranks(response.json())
                    snapshot = MarketCapRankSnapshot(
                        api_key_fingerprint=fingerprint,
                        ranks=MappingProxyType(ranks),
                        fetched_at=self._clock(),
                    )
                    self._snapshot = snapshot
                    return snapshot
                except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
                    logging.warning(
                        "CMC rank snapshot refresh attempt %s/%s failed: %s",
                        attempt,
                        REQUEST_ATTEMPTS,
                        exc,
                    )
                    if attempt < REQUEST_ATTEMPTS:
                        await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)

            return None

    @staticmethod
    def _parse_ranks(payload: Any) -> dict[str, int]:
        """Validate a provider response into a normalized rank mapping."""
        if not isinstance(payload, dict):
            raise ValueError("CMC payload is not an object")
        status = payload.get("status")
        if not isinstance(status, dict) or status.get("error_code") != 0:
            raise ValueError("CMC payload reports an error")
        entries = payload.get("data")
        if not isinstance(entries, list):
            raise ValueError("CMC payload data is not a list")

        ranks: dict[str, int] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            symbol = str(entry.get("symbol") or "").strip().upper()
            rank = entry.get("rank")
            if (
                symbol
                and isinstance(rank, int)
                and not isinstance(rank, bool)
                and rank > 0
            ):
                ranks.setdefault(symbol, rank)
        if not ranks:
            raise ValueError("CMC payload contains no valid ranks")
        return ranks


coin_market_cap_rank_service = CoinMarketCapRankService()
