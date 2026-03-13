"""Task orchestration helpers for watcher worker and symbol loops."""

import asyncio
from collections.abc import Callable
from typing import Any


def start_worker_tasks(
    task_names: list[str],
    create_worker_task: Callable[[str], asyncio.Task | None],
) -> list[asyncio.Task]:
    """Create the initial set of watcher worker tasks."""
    tasks: list[asyncio.Task] = []
    for task_name in task_names:
        task = create_worker_task(task_name)
        if task is not None:
            tasks.append(task)
    return tasks


def ensure_worker_tasks(
    worker_tasks: list[asyncio.Task],
    create_worker_task: Callable[[str], asyncio.Task | None],
    logger: Any,
) -> None:
    """Restart completed worker tasks in place."""
    for idx, task in enumerate(list(worker_tasks)):
        if not task.done():
            continue

        task_name = task.get_name()
        if task.cancelled():
            logger.warning("Worker task '%s' was cancelled; restarting.", task_name)
        else:
            exc = task.exception()
            if exc:
                logger.error(
                    "Worker task '%s' crashed; restarting. Cause: %s",
                    task_name,
                    exc,
                    exc_info=True,
                )
            else:
                logger.warning(
                    "Worker task '%s' stopped unexpectedly; restarting.",
                    task_name,
                )

        replacement = create_worker_task(task_name)
        if replacement is not None:
            worker_tasks[idx] = replacement


async def sync_symbol_tasks(
    symbol_tasks: dict[str, asyncio.Task],
    desired_symbols: set[str],
    create_symbol_task: Callable[[str], asyncio.Task],
    logger: Any,
    idle_sleep_seconds: float = 5.0,
) -> None:
    """Reconcile active watcher tasks with the desired symbol set."""
    current_symbols = set(symbol_tasks.keys())

    if not desired_symbols:
        logger.info("No active symbols to watch. Waiting for new trades...")
        for symbol, task in list(symbol_tasks.items()):
            task.cancel()
            del symbol_tasks[symbol]
        await asyncio.sleep(idle_sleep_seconds)
        return

    for symbol in desired_symbols - current_symbols:
        logger.info("Starting new watcher for %s", symbol)
        symbol_tasks[symbol] = create_symbol_task(symbol)

    for symbol in current_symbols - desired_symbols:
        logger.info("Stopping watcher for %s", symbol)
        task = symbol_tasks.pop(symbol)
        task.cancel()

    for symbol, task in list(symbol_tasks.items()):
        if task.done() and not task.cancelled():
            logger.warning("Watcher for %s crashed — restarting...", symbol)
            symbol_tasks[symbol] = create_symbol_task(symbol)
