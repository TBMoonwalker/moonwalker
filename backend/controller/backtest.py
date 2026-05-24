"""Backtest API endpoints."""

from datetime import UTC, datetime
from typing import Any

import helper
from controller.responses import json_response
from litestar.handlers import post
from service.backtest import Backtest, BacktestValidationError
from service.config import Config

logging = helper.LoggerFactory.get_logger("logs/controller.log", "controller_backtest")


@post("/backtest/run")
async def run_backtest(data: dict[str, Any]) -> Any:
    """Run a backtest with the given parameters."""
    return await _run_backtest(data)


async def _run_backtest(data: dict[str, Any]) -> Any:
    """Run a backtest with the given parameters."""
    symbol = data.get("symbol")
    strategy_slug = data.get("strategy_slug")
    trade_mode = str(data.get("trade_mode", "dynamic_dca")).strip().lower()
    if trade_mode == "sidestep" and not strategy_slug:
        strategy_slug = data.get("sidestep_reentry_strategy")
    timeframe = data.get("timeframe")
    start_date = data.get("start_date")
    end_date = data.get("end_date")

    if not all([symbol, strategy_slug, timeframe, start_date]):
        return json_response(
            {
                "error": "Missing required fields: symbol, strategy_slug, timeframe, start_date"
            },
            status_code=400,
        )

    try:
        start_dt = _parse_request_datetime(start_date, "start_date")
    except BacktestValidationError as exc:
        return json_response(
            {"error": str(exc), "code": "invalid_backtest_request"},
            status_code=400,
        )

    try:
        end_dt = (
            _parse_request_datetime(end_date, "end_date")
            if end_date
            else datetime.now(UTC)
        )
    except BacktestValidationError as exc:
        return json_response(
            {"error": str(exc), "code": "invalid_backtest_request"},
            status_code=400,
        )

    try:
        config_service = await Config.instance()
        config = config_service.snapshot()
        engine = Backtest(
            config=config,
            symbol=symbol,
            strategy_slug=strategy_slug,
            timeframe=timeframe,
            start_date=start_dt,
            end_date=end_dt,
            base_order_size=data.get("base_order_size", 10.0),
            take_profit_pct=data.get("take_profit_pct", 3.0),
            stop_loss_pct=data.get("stop_loss_pct"),
            max_safety_orders=data.get("max_safety_orders", 3),
            safety_order_step_pct=data.get("safety_order_step_pct", 10.0),
            fee=data.get("fee", 0.001),
            trade_mode=trade_mode,
            sidestep_bearish_strategy=data.get("sidestep_bearish_strategy"),
            sidestep_reentry_strategy=data.get("sidestep_reentry_strategy"),
        )
        result = await engine.run()
        return json_response(result)
    except BacktestValidationError as exc:
        return json_response(
            {"error": str(exc), "code": "invalid_backtest_request"},
            status_code=400,
        )
    except Exception as exc:  # noqa: BLE001 - controller must protect clients.
        logging.error(
            "Backtest failed for %s/%s: %s", symbol, timeframe, exc, exc_info=True
        )
        return json_response(
            {
                "error": "Backtest failed. Check server logs for details.",
                "code": "backtest_failed",
            },
            status_code=500,
        )


def _parse_request_datetime(value: Any, field: str) -> datetime:
    """Normalize API date payloads to timezone-aware UTC datetimes."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        raw = float(value)
        timestamp = raw / 1000 if raw > 10_000_000_000 else raw
        parsed = datetime.fromtimestamp(timestamp, tz=UTC)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise BacktestValidationError(f"{field} is required")
        if stripped.isdigit():
            parsed = _parse_request_datetime(int(stripped), field)
        else:
            try:
                parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            except ValueError as exc:
                raise BacktestValidationError(f"Invalid {field}: {value}") from exc
    else:
        raise BacktestValidationError(f"Invalid {field}: {value}")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


route_handlers = [run_backtest]
