"""Strategy chart indicator regression coverage."""

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
