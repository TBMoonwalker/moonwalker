"""Pure helpers for order persistence payload construction."""

import json
from datetime import datetime
from typing import Any

from service.exchange_types import ExchangeOrderPayload, SoldCheckStatus


def calculate_trade_duration(start_date_ms: float, end_date_ms: float) -> str:
    """Return trade duration as a JSON string from millisecond timestamps."""
    date1 = datetime.fromtimestamp(start_date_ms / 1000.0)
    date2 = datetime.fromtimestamp(end_date_ms / 1000.0)
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

    sell_date = closed_at or datetime.now()
    sell_timestamp_ms = sell_date.timestamp() * 1000
    open_date = datetime.fromtimestamp(open_timestamp_ms / 1000.0)
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
        "open_date": open_date,
        "close_date": sell_date,
        "duration": duration_data,
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
