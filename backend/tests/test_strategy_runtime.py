import pytest
from service import strategy_runtime
from service.strategy_runtime import GraphStrategyAdapter, StrategyEvaluationResult


@pytest.mark.asyncio
async def test_strategy_adapter_logs_first_result_and_suppresses_unchanged(
    monkeypatch,
) -> None:
    debug_calls: list[dict[str, object]] = []

    async def fake_evaluate_strategy_graph(*_args, **_kwargs):
        return StrategyEvaluationResult(False, 1, "no_match")

    def fake_debug(_message: str, payload: dict[str, object]) -> None:
        debug_calls.append(payload)

    monkeypatch.setattr(
        strategy_runtime,
        "evaluate_strategy_graph",
        fake_evaluate_strategy_graph,
    )
    monkeypatch.setattr(strategy_runtime.logging, "debug", fake_debug)
    monkeypatch.setattr(strategy_runtime, "_monotonic", lambda: 100.0)

    adapter = GraphStrategyAdapter("ema_swing", "4h")

    assert await adapter.run("UNI/USDC", "buy") is False
    assert await adapter.run("UNI/USDC", "buy") is False

    assert debug_calls == [
        {
            "symbol": "UNI/USDC",
            "strategy": "ema_swing",
            "version": 1,
            "side": "buy",
            "creating_order": False,
            "reason": "no_match",
        }
    ]


@pytest.mark.asyncio
async def test_strategy_adapter_logs_unchanged_heartbeat_after_interval(
    monkeypatch,
) -> None:
    debug_calls: list[dict[str, object]] = []
    monotonic_values = iter([100.0, 200.0, 2_000.0])

    async def fake_evaluate_strategy_graph(*_args, **_kwargs):
        return StrategyEvaluationResult(False, 1, "no_match")

    def fake_debug(_message: str, payload: dict[str, object]) -> None:
        debug_calls.append(payload)

    monkeypatch.setattr(
        strategy_runtime,
        "evaluate_strategy_graph",
        fake_evaluate_strategy_graph,
    )
    monkeypatch.setattr(strategy_runtime.logging, "debug", fake_debug)
    monkeypatch.setattr(strategy_runtime, "_monotonic", lambda: next(monotonic_values))

    adapter = GraphStrategyAdapter("ema_swing", "4h")

    await adapter.run("UNI/USDC", "buy")
    await adapter.run("UNI/USDC", "buy")
    await adapter.run("UNI/USDC", "buy")

    assert len(debug_calls) == 2
    assert debug_calls[1] == {
        "symbol": "UNI/USDC",
        "strategy": "ema_swing",
        "version": 1,
        "side": "buy",
        "creating_order": False,
        "reason": "no_match",
        "heartbeat": True,
        "unchanged_evaluations": 2,
        "seconds_since_last_log": 1900.0,
    }


@pytest.mark.asyncio
async def test_strategy_adapter_logs_changed_result_immediately(monkeypatch) -> None:
    debug_calls: list[dict[str, object]] = []
    results = iter(
        [
            StrategyEvaluationResult(False, 1, "no_match"),
            StrategyEvaluationResult(True, 1, "matched"),
        ]
    )

    async def fake_evaluate_strategy_graph(*_args, **_kwargs):
        return next(results)

    def fake_debug(_message: str, payload: dict[str, object]) -> None:
        debug_calls.append(payload)

    monkeypatch.setattr(
        strategy_runtime,
        "evaluate_strategy_graph",
        fake_evaluate_strategy_graph,
    )
    monkeypatch.setattr(strategy_runtime.logging, "debug", fake_debug)
    monkeypatch.setattr(strategy_runtime, "_monotonic", lambda: 100.0)

    adapter = GraphStrategyAdapter("ema_swing", "4h")

    assert await adapter.run("UNI/USDC", "buy") is False
    assert await adapter.run("UNI/USDC", "buy") is True

    assert debug_calls == [
        {
            "symbol": "UNI/USDC",
            "strategy": "ema_swing",
            "version": 1,
            "side": "buy",
            "creating_order": False,
            "reason": "no_match",
        },
        {
            "symbol": "UNI/USDC",
            "strategy": "ema_swing",
            "version": 1,
            "side": "buy",
            "creating_order": True,
            "reason": "matched",
        },
    ]


@pytest.mark.asyncio
async def test_strategy_health_check_logs_info_with_in_memory_state(
    monkeypatch,
) -> None:
    evaluate_calls: list[tuple[str, str, str, str, object]] = []
    info_calls: list[object] = []

    async def fake_evaluate_strategy_graph(
        slug,
        timeframe,
        symbol,
        side,
        *_args,
        **kwargs,
    ):
        matched = symbol == "BREV/USDC"
        evaluate_calls.append(
            (slug, timeframe, symbol, side, kwargs.get("state_store"))
        )
        return StrategyEvaluationResult(
            matched,
            7,
            "matched" if matched else "no_match",
        )

    def fake_info(_message: str, payload, *args) -> None:
        info_calls.append(payload if not args else (payload, *args))

    monkeypatch.setattr(
        strategy_runtime,
        "evaluate_strategy_graph",
        fake_evaluate_strategy_graph,
    )
    monkeypatch.setattr(strategy_runtime.logging, "info", fake_info)

    summary = await strategy_runtime.run_strategy_health_check(
        "ema_swing",
        "4h",
        ["BREV/USDC", "BARD/USDC", "BREV/USDC"],
    )

    assert summary.evaluated == 2
    assert summary.matched == 1
    assert summary.failed == 0
    assert [call[:4] for call in evaluate_calls] == [
        ("ema_swing", "4h", "BARD/USDC", "buy"),
        ("ema_swing", "4h", "BREV/USDC", "buy"),
    ]
    assert all(isinstance(call[4], dict) for call in evaluate_calls)
    assert info_calls[0] == {
        "source": "startup_health_check",
        "symbol": "BARD/USDC",
        "strategy": "ema_swing",
        "version": 7,
        "side": "buy",
        "creating_order": False,
        "reason": "no_match",
        "timeframe": "4h",
    }
