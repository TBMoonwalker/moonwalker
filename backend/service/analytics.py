"""Analytics service for closed-trade aggregation."""

from __future__ import annotations

import statistics as stdlib_stats
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import helper
import model
from service.ai_trust import build_analytics_payload

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
            overview = self._empty()
            overview["ai_trust"] = await build_analytics_payload()
            return overview

        overview = compute_stats_from_trades(rows)
        overview["ai_trust"] = await build_analytics_payload()
        return overview

    @staticmethod
    def compute_stats_from_trades(rows: list[Any]) -> dict[str, Any]:
        """Return analytics overview from in-memory trade rows."""
        return compute_stats_from_trades(rows)

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
        total_cost = round(sum((r.cost or 0.0) for r in rows), 2)

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
            ts = _date_str_to_epoch_ms(date_str, resolution)
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
    """Convert a date bucket key back to milliseconds."""
    try:
        if resolution == "weekly":
            parsed = datetime.strptime(f"{date_str}-1", "%G-W%V-%u")
            return int(parsed.replace(tzinfo=UTC).timestamp() * 1000)
        if date_str.startswith("2") and "-" in date_str:
            parsed = datetime.strptime(date_str, "%Y-%m-%d")
            return int(parsed.replace(tzinfo=UTC).timestamp() * 1000)
    except ValueError:
        pass
    return None


def _trade_value(row: Any, key: str, default: Any = None) -> Any:
    """Read a trade field from an ORM row or dictionary."""
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def compute_stats_from_trades(rows: list[Any]) -> dict[str, Any]:
    """Return analytics overview from ORM rows or synthetic trade dictionaries."""
    if not rows:
        return Analytics._empty()
    return {
        "summary": _summary_from_rows(rows),
        "heatmap_daily": _heatmap_from_rows(rows, "daily"),
        "heatmap_weekly": _heatmap_from_rows(rows, "weekly"),
        "per_symbol": _per_symbol_from_rows(rows),
        "duration_extremes": _duration_extremes_from_rows(rows),
        "drawdown": _drawdown_from_rows(rows),
        "distribution": _distribution_from_rows(rows),
    }


def _summary_from_rows(rows: list[Any]) -> dict[str, Any]:
    total = len(rows)
    profits = [_trade_value(r, "profit") for r in rows]
    profits = [p for p in profits if p is not None]
    profit_percents = [_trade_value(r, "profit_percent") for r in rows]
    profit_percents = [p for p in profit_percents if p is not None]
    durations: list[float] = []

    for r in rows:
        hours = helper.parse_duration_hours(
            _trade_value(r, "duration"),
            open_date=_trade_value(r, "open_date"),
            close_date=_trade_value(r, "close_date"),
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
    total_cost = round(sum((_trade_value(r, "cost") or 0.0) for r in rows), 2)

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


def _heatmap_from_rows(rows: list[Any], resolution: str) -> list[dict[str, Any]]:
    buckets: dict[str, int] = defaultdict(int)
    for r in rows:
        key = _extract_date_key(_trade_value(r, "close_date"), resolution)
        if key:
            buckets[key] += 1

    result: list[dict[str, Any]] = []
    for date_str, count in sorted(buckets.items()):
        ts = _date_str_to_epoch_ms(date_str, resolution)
        if ts is not None:
            result.append({"timestamp": ts, "value": count})
    return result


def _per_symbol_from_rows(rows: list[Any]) -> list[dict[str, Any]]:
    by_symbol: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        by_symbol[str(_trade_value(r, "symbol", ""))].append(r)

    result: list[dict[str, Any]] = []
    for symbol, trades in sorted(
        by_symbol.items(),
        key=lambda item: sum((_trade_value(t, "profit") or 0) for t in item[1]),
        reverse=True,
    ):
        total = len(trades)
        profits = [_trade_value(t, "profit") for t in trades]
        profits = [p for p in profits if p is not None]
        durations: list[float] = []
        for t in trades:
            hours = helper.parse_duration_hours(
                _trade_value(t, "duration"),
                open_date=_trade_value(t, "open_date"),
                close_date=_trade_value(t, "close_date"),
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


def _duration_extremes_from_rows(rows: list[Any]) -> dict[str, list[dict[str, Any]]]:
    with_duration: list[tuple[float, Any]] = []
    for r in rows:
        hours = helper.parse_duration_hours(
            _trade_value(r, "duration"),
            open_date=_trade_value(r, "open_date"),
            close_date=_trade_value(r, "close_date"),
        )
        if hours is not None:
            with_duration.append((hours, r))

    with_duration.sort(key=lambda item: item[0])
    shortest = with_duration[:5] if with_duration else []
    longest = with_duration[-5:] if with_duration else []

    def _trade_summary(hours: float, trade: Any) -> dict[str, Any]:
        profit = _trade_value(trade, "profit")
        profit_percent = _trade_value(trade, "profit_percent")
        return {
            "symbol": _trade_value(trade, "symbol"),
            "duration_hours": round(hours, 2),
            "duration_formatted": _format_duration(hours),
            "profit": round(profit, 2) if profit is not None else 0.0,
            "profit_percent": (
                round(profit_percent, 2) if profit_percent is not None else 0.0
            ),
            "close_date": _trade_value(trade, "close_date"),
            "deal_id": _trade_value(trade, "deal_id"),
        }

    return {
        "longest": [_trade_summary(h, t) for h, t in reversed(longest)],
        "shortest": [_trade_summary(h, t) for h, t in shortest],
    }


def _drawdown_from_rows(rows: list[Any]) -> dict[str, Any]:
    sorted_trades = sorted(
        (r for r in rows if _trade_value(r, "close_date")),
        key=lambda r: _trade_value(r, "close_date"),
    )
    if not sorted_trades:
        return {"max_drawdown": 0.0, "max_drawdown_percent": 0.0}

    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    worst_pct = 0.0

    for t in sorted_trades:
        cumulative += _trade_value(t, "profit") or 0.0
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


def _distribution_from_rows(rows: list[Any]) -> dict[str, Any]:
    profit_percents = [_trade_value(r, "profit_percent") for r in rows]
    profit_percents = [p for p in profit_percents if p is not None]
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
    std_dev = stdlib_stats.stdev(profit_percents) if len(profit_percents) >= 2 else 0.0

    return {
        "bins": bins,
        "median": round(median, 2),
        "std_dev": round(std_dev, 2),
        "best": round(max(profit_percents), 2),
        "worst": round(min(profit_percents), 2),
    }


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
    """Create profit histogram bins without crossing breakeven."""
    if not values:
        return []

    losses = [value for value in values if value < 0]
    breakeven_count = sum(1 for value in values if value == 0)
    profits = [value for value in values if value > 0]
    reserved_bins = 1 if breakeven_count else 0
    available_bins = max(1, num_bins - reserved_bins)

    if losses and profits:
        loss_bin_count = round(
            available_bins * len(losses) / (len(losses) + len(profits))
        )
        loss_bin_count = min(max(1, loss_bin_count), available_bins - 1)
        profit_bin_count = available_bins - loss_bin_count
    elif losses:
        loss_bin_count = available_bins
        profit_bin_count = 0
    else:
        loss_bin_count = 0
        profit_bin_count = available_bins

    bins: list[dict[str, Any]] = []
    bins.extend(_make_signed_histogram_bins(losses, loss_bin_count, "Loss"))
    if breakeven_count:
        bins.append(
            {
                "label": "Breakeven",
                "min": 0.0,
                "max": 0.0,
                "count": breakeven_count,
            }
        )
    bins.extend(_make_signed_histogram_bins(profits, profit_bin_count, "Profit"))
    return bins


def _make_signed_histogram_bins(
    values: list[float],
    target_bins: int,
    label: str,
) -> list[dict[str, Any]]:
    """Create evenly-spaced histogram bins for one side of breakeven."""
    if not values or target_bins <= 0:
        return []

    mn = min(values)
    mx = max(values)
    if mn == mx:
        return [
            {
                "label": label,
                "min": round(mn, 2),
                "max": round(mx, 2),
                "count": len(values),
            }
        ]

    bin_count = min(target_bins, len(values))
    width = (mx - mn) / bin_count
    bins: list[dict[str, Any]] = []
    for i in range(bin_count):
        lo = mn + width * i
        hi = mn + width * (i + 1)
        count = sum(
            1 for v in values if v >= lo and (v < hi if i < bin_count - 1 else v <= hi)
        )
        bins.append(
            {
                "label": label,
                "min": round(lo, 2),
                "max": round(hi, 2),
                "count": count,
            }
        )
    return bins
