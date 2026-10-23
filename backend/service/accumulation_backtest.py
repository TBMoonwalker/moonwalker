"""Run saved accumulation strategies through the normal historical-data backtest."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from service.accumulation_contracts import canonical_decimal
from service.accumulation_replay import run_accumulation_replay
from service.backtest import (
    BacktestValidationError,
    fetch_ohlcv,
    validate_backtest_range,
)
from service.strategy_runtime import load_accumulation_strategy_version


async def run_accumulation_backtest(
    config: dict[str, Any],
    data: dict[str, Any],
    start_date: datetime,
    end_date: datetime,
) -> dict[str, Any]:
    """Fetch completed candles and adapt the isolated replay to Backtest results."""
    symbol = data.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip() or len(symbol) > 64:
        raise BacktestValidationError("Select a spot symbol.")
    symbol = symbol.strip()
    if ":" in symbol or "/" not in symbol:
        raise BacktestValidationError("Accumulation backtests require a spot symbol.")
    version = await load_accumulation_strategy_version(data.get("strategy_version_id"))
    parameters = version.parameters
    if data.get("timeframe", parameters.timeframe) != parameters.timeframe:
        raise BacktestValidationError("Use the saved strategy version's timeframe.")
    funding = canonical_decimal(str(data.get("funding", "1000")), positive=True)
    slippage = canonical_decimal(str(data.get("slippage_bps", "20")))
    interval = data.get("fixed_interval_candles", 24)
    try:
        fee = Decimal(str(data.get("fee", "0.001")))
    except InvalidOperation as exc:
        raise BacktestValidationError(
            "Fee must be a finite fraction from 0 to 0.1."
        ) from exc
    if not fee.is_finite() or not 0 <= fee <= Decimal("0.1"):
        raise BacktestValidationError("Fee must be a finite fraction from 0 to 0.1.")
    if (
        Decimal(slippage) > 1000
        or type(interval) is not int
        or not 1 <= interval <= 20000
    ):
        raise BacktestValidationError(
            "Slippage must be 0..1000 bps; interval 1..20000 candles."
        )
    start_ms = int(start_date.timestamp() * 1000)
    end_ms = min(
        int(end_date.timestamp() * 1000),
        parameters.latest_close(int(datetime.now(UTC).timestamp() * 1000)),
    )
    # Begin evaluation at a complete bar opening within the requested range.
    first_open = parameters.latest_close(start_ms)
    if first_open < start_ms:
        first_open += parameters.interval_ms
    fetch_start = first_open - parameters.history_length * parameters.interval_ms
    validate_backtest_range(parameters.timeframe, fetch_start, end_ms)
    if fetch_start < 0 or end_ms - first_open < 2 * parameters.interval_ms:
        raise BacktestValidationError(
            "Select at least two completed evaluation candles with available warmup."
        )
    candles = await fetch_ohlcv(
        {**config, "market": "spot"},
        symbol,
        parameters.timeframe,
        fetch_start,
        end_ms,
        max_candles=20000,
    )
    candles = sorted(
        (
            candle
            for candle in candles
            if fetch_start <= candle.timestamp
            and candle.timestamp + parameters.interval_ms <= end_ms
        ),
        key=lambda candle: candle.timestamp,
    )
    warmup = [candle for candle in candles if candle.timestamp < first_open]
    evaluation = [candle for candle in candles if candle.timestamp >= first_open]
    if len(warmup) != parameters.history_length or len(evaluation) < 2:
        raise BacktestValidationError(
            "Exchange history does not cover the strategy warmup and selected evaluation range."
        )
    payload = {
        "candles": [
            {
                "close_ms": candle.timestamp + parameters.interval_ms,
                "open": str(candle.open),
                "high": str(candle.high),
                "low": str(candle.low),
                "close": str(candle.close),
            }
            for candle in candles
        ],
        "funding": funding,
        "fee_bps": str(fee * 10000),
        "slippage_bps": slippage,
        "fixed_interval_candles": interval,
    }
    # The bounded pure simulation is CPU work; market I/O remains async-native.
    report = await asyncio.to_thread(run_accumulation_replay, payload, parameters)
    for fill in report["accumulation_trades"]:
        fill["execution_price"] = str(
            (Decimal(fill["spent"]) - Decimal(fill["fee"])) / Decimal(fill["quantity"])
        )
    accumulation = next(
        row for row in report["results"] if row["strategy"] == "accumulation"
    )
    return {
        "trades": [],
        "chart": {
            "candles": [
                {
                    "time": candle.timestamp // 1000,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
                for candle in evaluation
            ],
            "markers": [
                {
                    "time": fill["execution_open_ms"] // 1000,
                    "position": "belowBar",
                    "color": "#2E7D5B",
                    "shape": "arrow_up",
                    "text": "Buy",
                }
                for fill in report["accumulation_trades"]
            ],
            "indicators": [],
        },
        "stats": {
            "symbol": symbol,
            "strategy": f"{version.slug} · v{version.version}",
            "strategy_version_id": version.id,
            "trade_mode": "accumulation",
            "timeframe": parameters.timeframe,
            "candles_fetched": len(candles),
            "candles_evaluated": len(evaluation),
            "warmup_candles": parameters.history_length,
            "still_open_at_end": Decimal(accumulation["units"]) > 0,
        },
        "accumulation": {**report, "strategy_version_id": version.id},
    }
