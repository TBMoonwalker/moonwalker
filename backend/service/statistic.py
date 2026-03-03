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
        rows: list[tuple[Any, Any]],
        now: datetime,
        timeline_horizons: dict[str, timedelta],
    ) -> list[dict[str, Any]]:
        """Build resampled profit timeline synchronously from raw rows."""
        df = pd.DataFrame(rows, columns=["timestamp", "profit_overall"])
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
            frames.append(
                year_slice["profit_overall"].resample("1W").last().dropna().to_frame()
            )

        month_slice = df[(df.index >= month_start) & (df.index < week_start)]
        if not month_slice.empty:
            frames.append(
                month_slice["profit_overall"].resample("1D").last().dropna().to_frame()
            )

        week_slice = df[(df.index >= week_start) & (df.index < day_start)]
        if not week_slice.empty:
            frames.append(
                week_slice["profit_overall"].resample("4h").last().dropna().to_frame()
            )

        day_slice = df[df.index >= day_start]
        if not day_slice.empty:
            frames.append(
                day_slice["profit_overall"].resample("15min").last().dropna().to_frame()
            )

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
            data = await model.ClosedTrades.filter(
                close_date__gt=begin_datetime
            ).values_list("close_date", "profit")

            for timestamp, profit_unit in data:
                date = (datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f")).date()
                if str(date) not in profit_data:
                    profit_data[str(date)] = profit_unit
                else:
                    profit_data[str(date)] += profit_unit

            profit_data = await asyncio.to_thread(
                self._resample_profit_data_sync, profit_data, period
            )

        except BaseORMException as e:
            # Broad catch to keep stats endpoints responsive.
            logging.error("Error getting profits for %s data: %s", period, e)

        return profit_data

    async def get_profit(self) -> dict[str, Any]:
        """Return profit, uPNL, and autopilot summaries."""
        return copy.deepcopy(await self._get_profit_cached())

    @helper.async_ttl_cache(maxsize=1, ttl=PROFIT_CACHE_TTL_SECONDS)
    async def _get_profit_cached(self) -> dict[str, Any]:
        """Compute and cache profit, uPNL, and autopilot summaries."""
        profit_data = {}

        # uPNL
        profit_data["upnl"] = 0
        try:
            upnl = await model.OpenTrades.annotate(total=Sum("profit")).values_list(
                "total", flat=True
            )
            if upnl[0]:
                profit_data["upnl"] = upnl[0]
        except BaseORMException as e:
            # Broad catch to keep stats endpoints responsive.
            logging.error("Error getting losses: %s", e)

        # Profit overall
        profit_data["profit_overall"] = 0
        try:
            profit = await model.ClosedTrades.annotate(total=Sum("profit")).values_list(
                "total", flat=True
            )
            closed_profit = float(profit[0] or 0.0)
            profit_data["profit_overall"] = closed_profit + float(
                profit_data["upnl"] or 0.0
            )

        except BaseORMException as e:
            # Broad catch to keep stats endpoints responsive.
            logging.error("Error getting profit: %s", e)

        # Funds locked in deals
        profit_data["funds_locked"] = 0
        try:
            funds_locked = await model.OpenTrades.annotate(
                total=Sum("cost")
            ).values_list("total", flat=True)
            profit_data["funds_locked"] = funds_locked[0]
        except BaseORMException as e:
            # Broad catch to keep stats endpoints responsive.
            logging.error("Error getting funds: %s", e)

        # Autopilot mode
        profit_data["autopilot"] = "none"
        try:
            autopilot = await model.Autopilot.all().order_by("-id").first()
            profit_data["autopilot"] = autopilot.mode if autopilot else "none"
        except BaseORMException as e:
            # Broad catch to keep stats endpoints responsive.
            logging.error("Error getting autopilot mode: %s", e)

        profit_data["profit_week"] = {}
        begin_week = (
            datetime.now() + timedelta(days=(0 - datetime.now().weekday()))
        ).date()
        try:
            profit_week = await model.ClosedTrades.filter(
                close_date__gt=begin_week
            ).values_list("close_date", "profit")
            for timestamp, profit_day in profit_week:
                date = (datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f")).date()
                if str(date) not in profit_data["profit_week"]:
                    profit_data["profit_week"][str(date)] = profit_day
                else:
                    profit_data["profit_week"][str(date)] += profit_day
        except BaseORMException as e:
            # Broad catch to keep stats endpoints responsive.
            logging.error("Error getting profits for the week: %s", e)

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
                .values_list("timestamp", "profit_overall")
            )
            for timestamp, profit_overall in rows:
                upnl_data.append(
                    {
                        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                        "profit_overall": profit_overall,
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
                .values_list("timestamp", "profit_overall")
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
            should_update_open_trade = not (
                stats["type"] == "tp_check" and bool(stats.get("sell"))
            )

            if should_update_open_trade:
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
                return
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
