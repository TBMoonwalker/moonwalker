"""Async cache helpers backed by cachetools."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from cachetools import TTLCache

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def async_ttl_cache(maxsize: int, ttl: int) -> Callable[[F], F]:
    """Cache async function results in a TTL cache.

    This is a minimal async wrapper around cachetools TTLCache to avoid
    depending on asyncache while keeping TTL + LRU behavior.
    """
    cache: TTLCache[Any, Any] = TTLCache(maxsize=maxsize, ttl=ttl)
    lock = asyncio.Lock()

    def decorator(func: F) -> F:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("async_ttl_cache can only be used with async functions")

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = (args, tuple(sorted(kwargs.items())))
            async with lock:
                if key in cache:
                    return cache[key]
            result = await func(*args, **kwargs)
            async with lock:
                cache[key] = result
            return result

        async def cache_clear() -> None:
            """Clear cached values for callers that mutate the backing store."""
            async with lock:
                cache.clear()

        wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
