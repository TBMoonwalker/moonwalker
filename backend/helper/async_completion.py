"""Finish cancellation-sensitive operations on the task that owns their cleanup."""

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

Result = TypeVar("Result")


async def finish_before_cancellation(
    operation: Coroutine[Any, Any, Result], *, name: str
) -> Result:
    """Defer caller cancellation until bounded work releases its DB resources.

    SQLite transaction entry can acquire its connection lock before awaiting
    BEGIN. Cancelling that entry can strand the lock. Keep entry and cleanup
    together on one owned task, drain it even after repeated cancellation, then
    propagate cancellation to the caller. The supplied operation must be bounded.
    """
    task = asyncio.create_task(operation, name=name)
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
        except Exception:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
    if cancelled:
        raise asyncio.CancelledError
    return result
