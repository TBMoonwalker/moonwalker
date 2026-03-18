import asyncio

import pytest
import service.watcher_tasks as watcher_tasks


class _Logger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def info(self, message: str, *args) -> None:
        self.messages.append(("info", message % args if args else message))

    def warning(self, message: str, *args) -> None:
        self.messages.append(("warning", message % args if args else message))

    def error(self, message: str, *args, **kwargs) -> None:
        self.messages.append(("error", message % args if args else message))


@pytest.mark.asyncio
async def test_start_worker_tasks_creates_named_tasks() -> None:
    async def noop() -> None:
        await asyncio.sleep(0)

    tasks = watcher_tasks.start_worker_tasks(
        ["worker:a", "worker:b"],
        lambda name: asyncio.create_task(noop(), name=name),
    )

    assert [task.get_name() for task in tasks] == ["worker:a", "worker:b"]

    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_ensure_worker_tasks_restarts_finished_worker() -> None:
    logger = _Logger()

    async def crash() -> None:
        raise RuntimeError("boom")

    crashed_task = asyncio.create_task(crash(), name="worker:a")
    await asyncio.sleep(0)

    async def noop() -> None:
        await asyncio.sleep(3600)

    worker_tasks = [crashed_task]
    watcher_tasks.ensure_worker_tasks(
        worker_tasks,
        lambda name: asyncio.create_task(noop(), name=name),
        logger,
    )

    replacement = worker_tasks[0]
    assert replacement is not crashed_task
    assert replacement.get_name() == "worker:a"
    assert any(level == "error" for level, _message in logger.messages)

    replacement.cancel()
    await asyncio.gather(replacement, return_exceptions=True)


@pytest.mark.asyncio
async def test_sync_symbol_tasks_reconciles_add_remove_and_restart() -> None:
    logger = _Logger()
    created: list[str] = []

    async def noop() -> None:
        await asyncio.sleep(3600)

    def create_symbol_task(symbol: str) -> asyncio.Task:
        created.append(symbol)
        return asyncio.create_task(noop(), name=f"watch:{symbol}")

    to_remove = asyncio.create_task(noop(), name="watch:OLD/USDC")

    async def crash() -> None:
        raise RuntimeError("boom")

    crashed = asyncio.create_task(crash(), name="watch:BTC/USDC")
    await asyncio.sleep(0)

    symbol_tasks = {
        "OLD/USDC": to_remove,
        "BTC/USDC": crashed,
    }
    await watcher_tasks.sync_symbol_tasks(
        symbol_tasks,
        {"BTC/USDC", "ETH/USDC"},
        create_symbol_task,
        logger,
        idle_sleep_seconds=0,
    )

    assert sorted(symbol_tasks.keys()) == ["BTC/USDC", "ETH/USDC"]
    assert created == ["ETH/USDC", "BTC/USDC"]
    assert crashed.done()
    assert isinstance(crashed.exception(), RuntimeError)
    await asyncio.gather(to_remove, return_exceptions=True)
    assert to_remove.cancelled()

    for task in symbol_tasks.values():
        task.cancel()
    await asyncio.gather(*symbol_tasks.values(), return_exceptions=True)
