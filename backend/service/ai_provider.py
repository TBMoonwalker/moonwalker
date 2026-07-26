"""Lifecycle-owned HTTP transport for local AI providers."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx


class AiProviderClient:
    """Share one bounded async HTTP connection pool across AI requests."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Create the shared client once."""
        async with self._lock:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    limits=httpx.Limits(
                        max_connections=8,
                        max_keepalive_connections=4,
                    )
                )

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        timeout_seconds: float,
    ) -> httpx.Response:
        """POST through the shared client with bounded timeout categories."""
        await self.start()
        assert self._client is not None
        timeout = httpx.Timeout(
            connect=min(2.0, timeout_seconds),
            read=timeout_seconds,
            write=timeout_seconds,
            pool=min(2.0, timeout_seconds),
        )
        return await self._client.post(url, json=json, timeout=timeout)

    async def close(self) -> None:
        """Close pooled provider connections."""
        async with self._lock:
            client = self._client
            self._client = None
        if client is not None:
            await client.aclose()


ai_provider_client = AiProviderClient()
