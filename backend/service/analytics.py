"""Analytics service for closed-trade aggregation."""

from __future__ import annotations

import statistics as stdlib_stats
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import helper
import model
from tortoise.functions import Sum

logging = helper.LoggerFactory.get_logger("logs/analytics.log", "analytics")

# Only touch recent data to keep queries fast on large datasets.
ANALYTICS_LOOKBACK_YEARS = 2


class Analytics:
    """On-demand aggregation over closed trades."""

    async def get_overview(self) -> dict[str, Any]:
        """Return a complete analytics overview from closed trades.

        Aggregates summary, heatmap, per-symbol, duration extremes, drawdown,
        and profit distribution in a single pass.
        """
        cutoff = datetime.now(UTC) - timedelta(days=ANALYTICS_LOOKBACK_YEARS * 365)

        rows = await model.ClosedTrades.filter(close_date__gte=cutoff.isoformat())

        if not rows:
            return self._empty()

        return {
            "summary": await self._summary(rows),
            "heatmap_daily": await self._heatmap(rows, "daily"),
            "heatmap_weekly": await self._heatmap(rows, "weekly"),
            "per_symbol": await self._per_symbol(rows),
            "duration_extremes": await self._duration_extremes(rows),
            "drawdown": await self._drawdown(rows),
            "distribution": await self._distribution(rows),
        }

    async def _summary(self, rows: list[model.ClosedTrades]) -> dict[str, Any]:
        total = len(rows)
        profits = [r.profit for r in rows if r.profit is not None]
        profit_percents = [
            r.profit_percent for r in rows if r.profit_percent is not None
        ]
        durations: list[float] = []

        for r in rows:
            hours = helper.parse_duration_hours(
                r.duration,
                open_date=r.open_date,
                close_date=r.close_date,
            )
            if hours is not None:
                durations.append(hours)

        profitable = sum(1 for p in profits if p > 0)
        total_profit = sum(profits) or 0.0
        avg_profit = sum(profits) / len(profits) if profits else 0.0
        avg_profit_pct = (
            sum(profit_percents) / len(profit_percents) if profit_percents else 0.0
        )
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        total_cost_result = (
            await model.ClosedTrades.filter(pk__in=[r.pk for r in rows])
            .annotate(__total=Sum("cost"))
            .values_list("__total", flat=True)
        )
        total_cost = (
            total_cost_result[0]
            if total_cost_result and total_cost_result[0] is not None
            else 0.0
        )

        return {
            "total_trades": total,
            "profit_trades": profitable,
            "loss_trades": total - profitable,
            "win_rate": round(profitable / total * 100, 2) if total else 0.0,
            "total_profit": round(total_profit, 2),
            "avg_profit": round(avg_profit, 2),
            "avg_profit_percent": round(avg_profit_pct, 2),
            "avg_duration_formatted": _format_duration(avg_duration),
            "total_cost": round(total_cost, 2),
        }

    async def _heatmap(
        self,
        rows: list[model.ClosedTrades],
        resolution: str,
    ) -> list[dict[str, Any]]:
        buckets: dict[str, int] = defaultdict(int)
        for r in rows:
            key = _extract_date_key(r.close_date, resolution)
            if key:
                buckets[key] += 1

        result: list[dict[str, Any]] = []
        for date_str, count in sorted(buckets.items()):
            ts = _date_str_to_epoch_ms(date_str)
            if ts is not None:
                result.append({"timestamp": ts, "value": count})
        return result

    async def _per_symbol(
        self,
        rows: list[model.ClosedTrades],
    ) -> list[dict[str, Any]]:
        by_symbol: dict[str, list[model.ClosedTrades]] = defaultdict(list)
        for r in rows:
            by_symbol[r.symbol].append(r)

        result: list[dict[str, Any]] = []
        for symbol, trades in sorted(
            by_symbol.items(),
            key=lambda item: sum((t.profit or 0) for t in item[1]),
            reverse=True,
        ):
            total = len(trades)
            profits = [t.profit for t in trades if t.profit is not None]
            durations: list[float] = []
            for t in trades:
                hours = helper.parse_duration_hours(
                    t.duration,
                    open_date=t.open_date,
                    close_date=t.close_date,
                )
                if hours is not None:
                    durations.append(hours)

            profitable = sum(1 for p in profits if p > 0)
            total_profit = sum(profits) or 0.0
            avg_profit = sum(profits) / len(profits) if profits else 0.0
            avg_duration = sum(durations) / len(durations) if durations else 0.0

            result.append(
                {
                    "symbol": symbol,
                    "trades": total,
                    "win_rate": round(profitable / total * 100, 2) if total else 0.0,
                    "total_profit": round(total_profit, 2),
                    "avg_profit": round(avg_profit, 2),
                    "avg_duration_formatted": _format_duration(avg_duration),
                }
            )
        return result

    async def _duration_extremes(
        self,
        rows: list[model.ClosedTrades],
    ) -> dict[str, list[dict[str, Any]]]:
        with_duration: list[tuple[float, model.ClosedTrades]] = []
        for r in rows:
            hours = helper.parse_duration_hours(
                r.duration,
                open_date=r.open_date,
                close_date=r.close_date,
            )
            if hours is not None:
                with_duration.append((hours, r))

        with_duration.sort(key=lambda item: item[0])

        shortest = with_duration[:5] if with_duration else []
        longest = with_duration[-5:] if with_duration else []

        def _trade_summary(hours: float, trade: model.ClosedTrades) -> dict[str, Any]:
            return {
                "symbol": trade.symbol,
                "duration_hours": round(hours, 2),
                "duration_formatted": _format_duration(hours),
                "profit": round(trade.profit, 2) if trade.profit is not None else 0.0,
                "profit_percent": (
                    round(trade.profit_percent, 2)
                    if trade.profit_percent is not None
                    else 0.0
                ),
                "close_date": trade.close_date,
                "deal_id": trade.deal_id,
            }

        return {
            "longest": [_trade_summary(h, t) for h, t in reversed(longest)],
            "shortest": [_trade_summary(h, t) for h, t in shortest],
        }

    async def _drawdown(
        self,
        rows: list[model.ClosedTrades],
    ) -> dict[str, Any]:
        sorted_trades = sorted(
            (r for r in rows if r.close_date), key=lambda r: r.close_date
        )
        if not sorted_trades:
            return {"max_drawdown": 0.0, "max_drawdown_percent": 0.0}

        cumulative = 0.0
        peak = 0.0
        worst = 0.0
        worst_pct = 0.0

        for t in sorted_trades:
            cumulative += t.profit or 0.0
            if cumulative > peak:
                peak = cumulative
            drawdown = peak - cumulative
            if drawdown > worst:
                worst = drawdown
                worst_pct = round(drawdown / abs(peak) * 100, 2) if peak != 0 else 0.0

        return {
            "max_drawdown": round(worst, 2),
            "max_drawdown_percent": worst_pct,
        }

    async def _distribution(
        self,
        rows: list[model.ClosedTrades],
    ) -> dict[str, Any]:
        profit_percents = [
            r.profit_percent for r in rows if r.profit_percent is not None
        ]
        if not profit_percents:
            return {
                "bins": [],
                "median": 0.0,
                "std_dev": 0.0,
                "best": 0.0,
                "worst": 0.0,
            }

        bins = _make_histogram_bins(profit_percents)
        median = stdlib_stats.median(profit_percents)
        std_dev = (
            stdlib_stats.stdev(profit_percents) if len(profit_percents) >= 2 else 0.0
        )

        return {
            "bins": bins,
            "median": round(median, 2),
            "std_dev": round(std_dev, 2),
            "best": round(max(profit_percents), 2),
            "worst": round(min(profit_percents), 2),
        }

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "summary": {
                "total_trades": 0,
                "profit_trades": 0,
                "loss_trades": 0,
                "win_rate": 0.0,
                "total_profit": 0.0,
                "avg_profit": 0.0,
                "avg_profit_percent": 0.0,
                "avg_duration_formatted": "0h 0m",
                "total_cost": 0.0,
            },
            "heatmap_daily": [],
            "heatmap_weekly": [],
            "per_symbol": [],
            "duration_extremes": {"longest": [], "shortest": []},
            "drawdown": {"max_drawdown": 0.0, "max_drawdown_percent": 0.0},
            "distribution": {
                "bins": [],
                "median": 0.0,
                "std_dev": 0.0,
                "best": 0.0,
                "worst": 0.0,
            },
        }


def _extract_date_key(
    close_date: str | None,
    resolution: str,
) -> str | None:
    """Parse close_date into a date key string."""
    if not close_date:
        return None

    dt = helper.parse_datetime(close_date)
    if dt is None:
        return None

    if resolution == "weekly":
        iso_cal = dt.isocalendar()
        return f"{iso_cal[0]}-W{iso_cal[1]:02d}"

    return dt.strftime("%Y-%m-%d")


def _date_str_to_epoch_ms(date_str: str, resolution: str = "daily") -> int | None:
    """Convert a 'YYYY-MM-DD' key back to milliseconds."""
    try:
        if date_str.startswith("2") and "-" in date_str:
            parsed = datetime.strptime(date_str, "%Y-%m-%d")
            return int(parsed.replace(tzinfo=UTC).timestamp() * 1000)
    except ValueError:
        pass
    return None


def _format_duration(hours: float) -> str:
    """Format decimal hours into 'Xd Yh Zm' style string."""
    if hours <= 0:
        return "0h 0m"
    days = int(hours // 24)
    remaining = hours - days * 24
    hrs = int(remaining // 1)
    mins = int((remaining - hrs) * 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hrs:
        parts.append(f"{hrs}h")
    parts.append(f"{mins}m")
    return " ".join(parts)


def _make_histogram_bins(
    values: list[float],
    num_bins: int = 10,
) -> list[dict[str, Any]]:
    """Create evenly-spaced histogram bins from a list of percentages."""
    if not values:
        return []
    mn = min(values)
    mx = max(values)
    if mn == mx:
        return [{"label": f"{mn:.1f}%", "min": mn, "max": mx, "count": len(values)}]
    width = (mx - mn) / num_bins
    bins: list[dict[str, Any]] = []
    for i in range(num_bins):
        lo = mn + width * i
        hi = mn + width * (i + 1)
        count = sum(
            1 for v in values if v >= lo and (v < hi if i < num_bins - 1 else v <= hi)
        )
        bins.append(
            {
                "label": f"{lo:.1f}%",
                "min": round(lo, 2),
                "max": round(hi, 2),
                "count": count,
            }
        )
    return bins
