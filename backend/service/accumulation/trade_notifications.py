"""Telegram trade notifications for settled accumulation fills.

The shared MonitoringService owns the transport, the monitoring_enabled gate
and the message format. This module only hands one settled accumulation fill
to that service; there is no second send path for accumulation trades.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

import helper
from service.accumulation.fill import AccumulationFill
from service.monitoring import MonitoringService

logging = helper.LoggerFactory.get_logger("logs/accumulation.log", "accumulation")


def build_accumulation_trade_payload(report: AccumulationFill) -> dict[str, Any]:
    """Build the monitoring payload for one settled accumulation fill."""
    with localcontext() as context:
        context.prec = 512
        filled = Decimal(report.filled)
        price = format(Decimal(report.quote_cost) / filled, "f") if filled > 0 else "0"
    return {
        "lifecycle": "accumulation",
        "symbol": report.symbol,
        "side": report.side,
        "timestamp": report.timestamp_ms,
        "amount": report.filled,
        "ordersize": report.quote_cost,
        "price": price,
        "fees": dict(report.fees),
        "order_id": report.order_id,
    }


async def notify_accumulation_trade(
    report: AccumulationFill, config: dict[str, Any]
) -> None:
    """Send the Telegram trade message for one newly settled fill.

    A failed send or formatting error is logged and never breaks the
    committed accounting that already ran, mirroring the input-observer rule.
    """
    try:
        await MonitoringService().notify_trade(
            f"trade.{report.side}",
            build_accumulation_trade_payload(report),
            config,
        )
    except Exception:  # noqa: BLE001 - notifications cannot fail committed accounting.
        logging.exception(
            "Accumulation trade notification failed for %s (%s).",
            report.symbol,
            report.order_id,
        )
