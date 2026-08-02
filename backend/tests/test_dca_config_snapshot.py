"""Task-local config isolation for concurrent DCA evaluations."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from service.dca import Dca


@pytest.mark.asyncio
async def test_concurrent_tickers_keep_independent_config_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dca = Dca()
    both_entered = asyncio.Event()
    entered = 0
    observed: dict[str, list[str]] = {"first": [], "second": []}

    async def capture_config(ticker: dict[str, Any]) -> None:
        nonlocal entered
        name = str(ticker["name"])
        observed[name].append(str((dca.config or {}).get("marker")))
        entered += 1
        if entered == 2:
            both_entered.set()
        await both_entered.wait()
        await asyncio.sleep(0)
        observed[name].append(str((dca.config or {}).get("marker")))

    monkeypatch.setattr(dca, "_process_ticker_data", capture_config)

    await asyncio.gather(
        dca.process_ticker_data({"name": "first"}, {"marker": "alpha"}),
        dca.process_ticker_data({"name": "second"}, {"marker": "beta"}),
    )

    assert observed == {
        "first": ["alpha", "alpha"],
        "second": ["beta", "beta"],
    }
    assert dca.config is None
