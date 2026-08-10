"""Strategy chart indicator regression coverage."""

from types import SimpleNamespace

import pytest
import service.strategy_runtime as runtime_module

from service.strategy_chart_indicators import StrategyChartIndicatorBuilder


def test_chart_indicator_builder_reports_long_ema_warmup() -> None:
    """EMA200 overlays need enough source candles before the visible window."""
    builder = StrategyChartIndicatorBuilder("BTC/USDC", "4h")

    builder.collect_ir_requirements(
        {
            "nodes": [
                {
                    "id": "ema200",
                    "type": "indicator",
                    "params": {"indicator": "ema", "length": 200},
                },
                {
                    "id": "ema20",
                    "type": "indicator",
                    "params": {"indicator": "ema", "length": 20},
                },
            ]
        }
    )

    assert builder.required_warmup_candles() == 400


@pytest.mark.asyncio
async def test_versioned_requirements_deduplicate_and_isolate_bad_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int | None]] = []

    async def fake_load_snapshot(
        slug: str,
        *,
        version: int | None = None,
    ) -> SimpleNamespace:
        calls.append((slug, version))
        if slug == "broken":
            raise ValueError("invalid historical strategy")
        indicator = "ema" if version == 1 else "rsi"
        return SimpleNamespace(
            ir={
                "nodes": [
                    {
                        "id": f"{indicator}-{version}",
                        "type": "indicator",
                        "params": {"indicator": indicator, "length": 20},
                    }
                ]
            }
        )

    monkeypatch.setattr(runtime_module, "_load_strategy_snapshot", fake_load_snapshot)
    builder = StrategyChartIndicatorBuilder("BTC/USDC", "4h")

    loaded = await builder.collect_versioned_strategy_requirements(
        [
            ("ema_swing", 1),
            ("ema_swing", 1),
            ("broken", 2),
            ("ema_swing", 2),
            ("", None),
        ]
    )

    assert calls == [("ema_swing", 1), ("broken", 2), ("ema_swing", 2)]
    assert loaded == ["ema_swing"]
    assert builder.required_warmup_candles() == 200
