"""Statistics aggregation for trading performance."""

import asyncio
import copy
from datetime import datetime, timedelta, timezone
from typing import Any

import helper
import model
import pandas as pd
from service.database import run_sqlite_write_with_retry
from service.trades import Trades
from tortoise.exceptions import BaseORMException
from tortoise.functions import Sum

logging = helper.LoggerFactory.get_logger("logs/statistics.log", "statistic")


class Statistic:
    """Compute and persist trading statistics."""

    PROFIT_CACHE_TTL_SECONDS = 2

    def __init__(self) -> None:
        self.trades = Trades()
        self.snapshot_interval_seconds = 60
        self.timeline_horizons = {
            "day": timedelta(days=1),
            "week": timedelta(days=7),
            "month": timedelta(days=30),
            "year": timedelta(days=365),
        }

    @staticmethod
    def _extract_date_key(timestamp: Any) -> str | None:
        """Normalize timestamp-like values into a YYYY-MM-DD grouping key."""
        if isinstance(timestamp, datetime):
            return timestamp.date().isoformat()
        if isinstance(timestamp, str):
            date_part = timestamp.strip().split(" ", maxsplit=1)[0]
            return date_part or None
        return None

    @classmethod
    def _group_profit_rows_by_date(
        cls, rows: list[tuple[Any, Any]]
    ) -> dict[str, float]:
        """Aggregate profit rows by date without reparsing full timestamps repeatedly."""
        grouped: dict[str, float] = {}
        for timestamp, profit_value in rows:
            date_key = cls._extract_date_key(timestamp)
            if not date_key:
                continue
            grouped[date_key] = grouped.get(date_key, 0.0) + float(profit_value or 0.0)
        return grouped

    async def _get_sum_value(
        self,
        queryset,
        field_name: str,
        error_message: str,
    ) -> float:
        """Return a scalar SUM aggregate with a stable 0.0 fallback."""
        try:
            result = await queryset.annotate(total=Sum(field_name)).values_list(
                "total", flat=True
            )
            return float(result[0] or 0.0)
        except BaseORMException as exc:
            logging.error(error_message, exc)
            return 0.0

    async def _get_profit_rows_since(
        self,
        begin_datetime: datetime | Any,
        error_message: str,
    ) -> list[tuple[Any, Any]]:
        """Return closed-trade profit rows since the given date boundary."""
        try:
            return await model.ClosedTrades.filter(
                close_date__gt=begin_datetime
            ).values_list("close_date", "profit")
        except BaseORMException as exc:
            logging.error(error_message, exc)
            return []

    async def _get_autopilot_mode(self) -> str:
        """Return the latest autopilot mode with a stable fallback."""
        try:
            autopilot = await model.Autopilot.all().order_by("-id").first()
            return autopilot.mode if autopilot else "none"
        except BaseORMException as exc:
            logging.error("Error getting autopilot mode: %s", exc)
            return "none"

    @staticmethod
    def _resample_profit_data_sync(
        profit_data: dict[str, Any], period: str
    ) -> dict[str, Any]:
        """Resample aggregated profit data synchronously."""
        if not profit_data:
            return profit_data
        s = pd.Series(profit_data)
        s.index = pd.to_datetime(s.index)
        if period == "monthly":
            result = s.resample("ME").sum().reset_index()
            result.columns = ["Month", "Sum"]
            return dict(zip(result["Month"].dt.strftime("%Y-%m"), result["Sum"]))
        if period == "yearly":
            result = s.resample("YE").sum().reset_index()
            result.columns = ["Year", "Sum"]
            return dict(zip(result["Year"].dt.strftime("%Y"), result["Sum"]))
        return profit_data

    @staticmethod
    def _build_profit_overall_timeline_sync(
        rows: list[tuple[Any, Any, Any]],
        now: datetime,
        timeline_horizons: dict[str, timedelta],
    ) -> list[dict[str, Any]]:
        """Build resampled profit timeline synchronously from raw rows."""
        df = pd.DataFrame(
            rows,
            columns=["timestamp", "profit_overall", "funds_locked"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        df = df[~df.index.duplicated(keep="last")]

        year_start = now - timeline_horizons["year"]
        day_start = now - timeline_horizons["day"]
        week_start = now - timeline_horizons["week"]
        month_start = now - timeline_horizons["month"]

        frames: list[pd.DataFrame] = []

        year_slice = df[(df.index >= year_start) & (df.index < month_start)]
        if not year_slice.empty:
            frames.append(year_slice.resample("1W").last().dropna())

        month_slice = df[(df.index >= month_start) & (df.index < week_start)]
        if not month_slice.empty:
            frames.append(month_slice.resample("1D").last().dropna())

        week_slice = df[(df.index >= week_start) & (df.index < day_start)]
        if not week_slice.empty:
            frames.append(week_slice.resample("4h").last().dropna())

        day_slice = df[df.index >= day_start]
        if not day_slice.empty:
            frames.append(day_slice.resample("15min").last().dropna())

        if not frames:
            return []

        merged = pd.concat(frames).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]

        timeline: list[dict[str, Any]] = []
        for timestamp, row in merged.iterrows():
            timeline.append(
                {
                    "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "profit_overall": float(row["profit_overall"]),
                    "funds_locked": float(row["funds_locked"]),
                }
            )
        return timeline

    async def get_profits_overall(
        self, timestamp: int | None, period: str = "daily"
    ) -> dict[str, Any] | None:
        """Return aggregated profits for the given time period."""
        profit_data = {}
        date = datetime.now()
        if timestamp:
            date = datetime.fromtimestamp(int(timestamp))
        match period:
            case "daily":
                begin_datetime = (date.replace(day=1)).date()
            case "monthly":
                begin_datetime = (date.replace(month=1)).date()
            case "yearly":
                begin_datetime = (date.replace(year=1)).date()
            case _:
                return None
        try:
            data = await self._get_profit_rows_since(
                begin_datetime,
                f"Error getting profits for {period} data: %s",
            )
            profit_data = self._group_profit_rows_by_date(data)
            profit_data = await asyncio.to_thread(
                self._resample_profit_data_sync, profit_data, period
            )

        except BaseORMException as e:
            logging.error("Error getting profits for %s data: %s", period, e)

        return profit_data

    async def get_profit(self) -> dict[str, Any]:
        """Return profit, uPNL, and autopilot summaries."""
        return copy.deepcopy(await self._get_profit_cached())

    @helper.async_ttl_cache(maxsize=1, ttl=PROFIT_CACHE_TTL_SECONDS)
    async def _get_profit_cached(self) -> dict[str, Any]:
        """Compute and cache profit, uPNL, and autopilot summaries."""
        profit_data = {}
        begin_week = (
            datetime.now() + timedelta(days=(0 - datetime.now().weekday()))
        ).date()

        upnl_task = self._get_sum_value(
            model.OpenTrades,
            "profit",
            "Error getting losses: %s",
        )
        closed_profit_task = self._get_sum_value(
            model.ClosedTrades,
            "profit",
            "Error getting profit: %s",
        )
        funds_locked_task = self._get_sum_value(
            model.OpenTrades,
            "cost",
            "Error getting funds: %s",
        )
        autopilot_task = self._get_autopilot_mode()
        profit_week_task = self._get_profit_rows_since(
            begin_week,
            "Error getting profits for the week: %s",
        )

        (
            upnl_value,
            closed_profit,
            funds_locked,
            autopilot_mode,
            profit_week_rows,
        ) = await asyncio.gather(
            upnl_task,
            closed_profit_task,
            funds_locked_task,
            autopilot_task,
            profit_week_task,
        )

        # uPNL
        profit_data["upnl"] = upnl_value

        # Profit overall
        profit_data["profit_overall"] = closed_profit + float(
            profit_data["upnl"] or 0.0
        )

        # Funds locked in deals
        profit_data["funds_locked"] = funds_locked

        # Autopilot mode
        profit_data["autopilot"] = autopilot_mode

        profit_data["profit_week"] = self._group_profit_rows_by_date(profit_week_rows)

        profit_data["profit_overall_timestamp"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        await self._store_upnl_snapshot(profit_data)
        return profit_data

    async def _store_upnl_snapshot(self, profit_data: dict[str, Any]) -> None:
        """Persist a sampled uPNL snapshot for long-term charting."""
        try:
            latest_snapshot = (
                await model.UpnlHistory.all().order_by("-timestamp").first()
            )
            now = datetime.now(timezone.utc)
            if latest_snapshot:
                latest_ts = latest_snapshot.timestamp
                if latest_ts.tzinfo is None:
                    latest_ts = latest_ts.replace(tzinfo=timezone.utc)
                elapsed = (now - latest_ts).total_seconds()
                if elapsed < self.snapshot_interval_seconds:
                    return

            await run_sqlite_write_with_retry(
                lambda: model.UpnlHistory.create(
                    timestamp=now,
                    upnl=float(profit_data.get("upnl") or 0.0),
                    profit_overall=float(profit_data.get("profit_overall") or 0.0),
                    funds_locked=float(profit_data.get("funds_locked") or 0.0),
                ),
                "storing upnl snapshot",
            )
        except BaseORMException as e:
            # Broad catch to avoid stats persistence failures affecting websocket data.
            logging.error("Error storing uPNL snapshot: %s", e)

    async def get_upnl_history_all(self) -> list[dict[str, Any]]:
        """Return overall profit snapshots from the beginning, ordered by timestamp."""
        upnl_data: list[dict[str, Any]] = []
        try:
            rows = (
                await model.UpnlHistory.all()
                .order_by("timestamp")
                .values_list("timestamp", "profit_overall", "funds_locked")
            )
            for timestamp, profit_overall, funds_locked in rows:
                upnl_data.append(
                    {
                        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                        "profit_overall": profit_overall,
                        "funds_locked": funds_locked,
                    }
                )
        except BaseORMException as e:
            # Broad catch to keep stats endpoints responsive.
            logging.error("Error getting uPNL history: %s", e)

        return upnl_data

    async def get_profit_overall_timeline(self) -> list[dict[str, Any]]:
        """Return last-12-month timeline with multi-resolution buckets.

        Resolution windows:
        - day: 15min
        - week: 4h
        - month: 1d
        - year: 1w
        """
        now = datetime.now(timezone.utc)
        year_start = now - self.timeline_horizons["year"]
        try:
            rows = (
                await model.UpnlHistory.filter(timestamp__gte=year_start)
                .order_by("timestamp")
                .values_list("timestamp", "profit_overall", "funds_locked")
            )
            if not rows:
                return []
            return await asyncio.to_thread(
                self._build_profit_overall_timeline_sync,
                rows,
                now,
                self.timeline_horizons,
            )
        except BaseORMException as e:
            # Broad catch to keep stats endpoints responsive.
            logging.error("Error getting profit-overall timeline: %s", e)
            return []

    async def update_statistic_data(self, stats: dict[str, Any]) -> None:
        """Update open trade statistics based on recent ticker data."""
        if stats["type"] != "dca_check":
            profit = (
                stats["current_price"] * stats["total_amount"] - stats["total_cost"]
            )
            open_timestamp = datetime.timestamp(datetime.now()) * 1000

            base_order = await self.trades.get_trade_by_ordertype(
                stats["symbol"], baseorder=True
            )

            try:
                if base_order and base_order[0].get("timestamp") is not None:
                    open_timestamp = float(base_order[0]["timestamp"])
                else:
                    logging.debug(
                        "Did not find base-order timestamp for %s; using current time.",
                        stats["symbol"],
                    )
            except (KeyError, IndexError, TypeError, ValueError) as e:
                logging.debug(
                    "Invalid base-order timestamp for %s; using current time. Cause %s",
                    stats["symbol"],
                    e,
                )
        else:
            if stats["new_so"]:
                logging.info("SO buy: %s", stats)

            # Update SO count statistics
            payload = {"so_count": stats["so_orders"]}
            await self.trades.update_open_trades(payload, stats["symbol"])
            logging.trace("%s", stats)

        # Comes from DCA module
        if stats["type"] == "tp_check":
            if stats.get("sell"):
                logging.info("TP sell: %s", stats)
            else:
                logging.trace("%s", stats)

            # Update open trade statistics
            payload = {
                "profit": profit,
                "profit_percent": stats["actual_pnl"],
                "amount": stats["total_amount"],
                "cost": stats["total_cost"],
                "current_price": stats["current_price"],
                "tp_price": stats["tp_price"],
                "avg_price": stats["avg_price"],
                "open_date": open_timestamp,
            }
            await self.trades.update_open_trades(payload, stats["symbol"])
