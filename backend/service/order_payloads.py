"""Pure helpers for order persistence payload construction."""

import json
from datetime import datetime, timezone
from typing import Any

from service.exchange_types import (
    ExchangeOrderPayload,
    SoldCheckStatus,
    TradeExecutionPayload,
)


def normalize_trade_datetime(value: datetime) -> datetime:
    """Normalize trade timestamps to timezone-aware UTC datetimes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def trade_datetime_from_ms(timestamp_ms: float) -> datetime:
    """Return a UTC datetime for a Unix millisecond timestamp."""
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)


def format_trade_datetime(value: datetime) -> str:
    """Return a stable text timestamp with an explicit UTC offset."""
    return normalize_trade_datetime(value).isoformat(sep=" ")


def calculate_trade_duration(start_date_ms: float, end_date_ms: float) -> str:
    """Return trade duration as a JSON string from millisecond timestamps."""
    date1 = trade_datetime_from_ms(start_date_ms)
    date2 = trade_datetime_from_ms(end_date_ms)
    time_difference = date2 - date1

    days = time_difference.days
    seconds = time_difference.seconds
    hours, reminder = divmod(seconds, 3600)
    minutes, seconds = divmod(reminder, 60)

    return json.dumps(
        {
            "days": days,
            "hours": hours,
            "minutes": minutes,
            "seconds": seconds,
        }
    )


def build_closed_trade_payloads(
    order_status: SoldCheckStatus,
    *,
    so_count: int,
    open_timestamp_ms: float,
    partial_amount: float = 0.0,
    partial_proceeds: float = 0.0,
    closed_at: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Build persistence and monitoring payloads for a completed sell."""
    symbol = str(order_status["symbol"])
    total_cost = float(order_status.get("total_cost") or 0.0)

    final_amount = float(order_status.get("total_amount") or 0.0)
    final_price = float(order_status.get("price") or 0.0)
    total_amount = partial_amount + final_amount
    total_proceeds = partial_proceeds + (final_amount * final_price)

    avg_sell_price = float(order_status.get("tp_price") or final_price or 0.0)
    avg_buy_price = float(order_status.get("avg_price") or 0.0)
    profit = float(order_status.get("profit") or 0.0)
    profit_percent = float(order_status.get("profit_percent") or 0.0)

    if total_amount > 0:
        avg_sell_price = total_proceeds / total_amount
        avg_buy_price = total_cost / total_amount if total_cost else 0.0
        profit = total_proceeds - total_cost
        profit_percent = (
            ((avg_sell_price - avg_buy_price) / avg_buy_price) * 100
            if avg_buy_price > 0
            else 0.0
        )

    sell_timestamp_raw = order_status.get("timestamp")
    if closed_at is not None:
        sell_date = normalize_trade_datetime(closed_at)
    elif sell_timestamp_raw is not None:
        sell_date = trade_datetime_from_ms(float(sell_timestamp_raw))
    else:
        sell_date = datetime.now(timezone.utc)
    sell_timestamp_ms = sell_date.timestamp() * 1000
    open_date = trade_datetime_from_ms(open_timestamp_ms)
    duration_data = calculate_trade_duration(open_timestamp_ms, sell_timestamp_ms)

    payload = {
        "symbol": symbol,
        "so_count": so_count,
        "profit": profit,
        "profit_percent": profit_percent,
        "amount": total_amount,
        "cost": total_cost,
        "tp_price": avg_sell_price,
        "avg_price": avg_buy_price,
        "open_date": format_trade_datetime(open_date),
        "close_date": format_trade_datetime(sell_date),
        "duration": duration_data,
        "sell_executions": build_final_sell_executions(
            order_status,
            closed_at=sell_date,
        ),
    }
    monitor_payload = {
        "symbol": symbol,
        "side": "sell",
        "amount": total_amount,
        "cost": total_cost,
        "avg_price": avg_buy_price,
        "tp_price": avg_sell_price,
        "profit": profit,
        "profit_percent": profit_percent,
        "so_count": so_count,
        "open_date": open_date.isoformat(),
        "close_date": sell_date.isoformat(),
        "duration": duration_data,
    }
    return {"payload": payload, "monitor_payload": monitor_payload}


def build_final_sell_executions(
    order_status: SoldCheckStatus,
    *,
    closed_at: datetime,
) -> list[TradeExecutionPayload]:
    """Return execution rows for the final sell status payload."""
    executions = list(order_status.get("executions") or [])
    if executions:
        return executions

    amount = float(order_status.get("total_amount") or 0.0)
    if amount <= 0:
        return []

    timestamp = int(
        float(order_status.get("timestamp") or closed_at.timestamp() * 1000)
    )
    return [
        {
            "symbol": str(order_status["symbol"]),
            "side": str(order_status.get("side") or "sell"),
            "role": "final_sell",
            "timestamp": str(timestamp),
            "price": float(order_status.get("price") or 0.0),
            "amount": amount,
            "ordersize": float(
                order_status.get("ordersize")
                or amount * float(order_status.get("price") or 0.0)
            ),
            "fee": float(
                order_status.get("base_fee") or order_status.get("amount_fee") or 0.0
            ),
            "order_id": (
                str(order_status.get("orderid"))
                if order_status.get("orderid") is not None
                else None
            ),
            "order_type": (
                str(order_status.get("ordertype"))
                if order_status.get("ordertype") is not None
                else None
            ),
        }
    ]


def build_buy_trade_payload(order_status: ExchangeOrderPayload) -> dict[str, Any]:
    """Build the trade-row payload for a filled exchange buy."""
    return {
        "timestamp": order_status["timestamp"],
        "ordersize": order_status["ordersize"],
        "fee": order_status["fees"],
        "precision": order_status["precision"],
        "amount_fee": order_status["amount_fee"],
        "amount": order_status["amount"],
        "price": order_status["price"],
        "symbol": order_status["symbol"],
        "orderid": order_status["orderid"],
        "bot": order_status["botname"],
        "ordertype": order_status["ordertype"],
        "baseorder": order_status["baseorder"],
        "safetyorder": order_status["safetyorder"],
        "order_count": order_status["order_count"],
        "so_percentage": order_status["so_percentage"],
        "direction": order_status["direction"],
        "side": order_status["side"],
        "signal_name": order_status.get("signal_name"),
        "strategy_name": order_status.get("strategy_name"),
        "timeframe": order_status.get("timeframe"),
        "metadata_json": order_status.get("metadata_json"),
    }


def build_buy_monitor_payload(order_status: ExchangeOrderPayload) -> dict[str, Any]:
    """Build the monitoring payload for a filled exchange buy."""
    return {
        "symbol": order_status["symbol"],
        "side": "buy",
        "timestamp": order_status["timestamp"],
        "ordersize": order_status["ordersize"],
        "price": order_status["price"],
        "amount": order_status["amount"],
        "bot": order_status["botname"],
        "ordertype": order_status["ordertype"],
        "baseorder": order_status["baseorder"],
        "safetyorder": order_status["safetyorder"],
        "order_count": order_status["order_count"],
        "so_percentage": order_status["so_percentage"],
        "signal_name": order_status.get("signal_name"),
        "strategy_name": order_status.get("strategy_name"),
        "timeframe": order_status.get("timeframe"),
        "metadata_json": order_status.get("metadata_json"),
    }


def build_manual_buy_trade_payload(
    *,
    normalized_symbol: str,
    timestamp_ms: int,
    price: float,
    amount: float,
    ordersize: float,
    amount_precision: int,
    order_count: int,
    so_percentage: float,
    trade_data: dict[str, Any],
) -> dict[str, Any]:
    """Build the trade-row payload for a manual safety-order add."""
    return {
        "timestamp": str(int(timestamp_ms)),
        "ordersize": float(ordersize),
        "fee": 0.0,
        "precision": amount_precision,
        "amount_fee": 0.0,
        "amount": float(amount),
        "price": float(price),
        "symbol": normalized_symbol,
        "orderid": (
            f"manual-add-{normalized_symbol.replace('/', '')}-"
            f"{int(timestamp_ms)}-{order_count}"
        ),
        "bot": str(trade_data.get("bot") or "manual_add"),
        "ordertype": str(trade_data.get("ordertype") or "market"),
        "baseorder": False,
        "safetyorder": True,
        "order_count": order_count,
        "so_percentage": so_percentage,
        "direction": str(trade_data.get("direction") or "long"),
        "side": "buy",
    }


def build_manual_buy_open_trade_payload(
    *,
    open_trade: dict[str, Any],
    amount: float,
    ordersize: float,
    order_count: int,
    tp_percent: float,
) -> dict[str, Any]:
    """Build the open-trade update payload for a manual safety-order add."""
    total_amount = float(open_trade.get("amount") or 0.0) + amount
    total_cost = float(open_trade.get("cost") or 0.0) + ordersize
    avg_price = total_cost / total_amount if total_amount > 0 else 0.0
    tp_price = avg_price * (1 + (tp_percent / 100.0)) if tp_percent else 0.0

    return {
        "so_count": max(int(open_trade.get("so_count") or 0), order_count),
        "amount": total_amount,
        "cost": total_cost,
        "avg_price": avg_price,
        "tp_price": tp_price,
        "unsellable_amount": 0.0,
        "unsellable_reason": None,
        "unsellable_min_notional": None,
        "unsellable_estimated_notional": None,
        "unsellable_since": None,
        "unsellable_notice_sent": False,
    }
