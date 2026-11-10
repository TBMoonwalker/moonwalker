"""Statistics aggregation for trading performance."""

import asyncio
import copy
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import helper
import model
import pandas as pd
from service.autopilot import Autopilot
from service.capital_budget import CapitalBudgetService
from service.config import Config
from service.database import run_sqlite_write_with_retry
from service.green_phase import AVAILABLE_QUOTE_UNSET
from service.order_payloads import format_trade_datetime, trade_datetime_from_ms
from service.realized_trades import (
    has_unverified_manual_stop_profit,
    realized_closed_trades,
)
from service.trades import Trades
from tortoise import Tortoise
from tortoise.exceptions import BaseORMException
from tortoise.functions import Sum

logging = helper.LoggerFactory.get_logger("logs/statistics.log", "statistic")
PROFIT_TIMELINE_HORIZON = timedelta(days=365)
# Resampled timeline cache lifetime. Matches the snapshot cadence so a
# timeline is at most one snapshot interval behind when no snapshot was
# stored; stored snapshots invalidate the cache immediately.
TIMELINE_CACHE_TTL_SECONDS = 60

# Process-wide generation of the uPNL snapshot data. Any Statistic instance
# (the controller graph, the DCA engine, a signal plugin) may store the next
# snapshot, so a cached timeline is only valid while this generation is
# unchanged; it advances once per stored snapshot.
_timeline_generation = 0

# Resolution of the adaptive timeline grid, in seconds, newest slice first.
# The year slice uses Monday-anchored weeks: pandas ``resample("1W")`` bins
# start on Monday and carry the label of the Sunday midnight inside the bin,
# so the year-slice label sits six days after the bucket start.
_TIMELINE_DAY_BUCKET_SECONDS = 15 * 60
_TIMELINE_WEEK_BUCKET_SECONDS = 4 * 3600
_TIMELINE_MONTH_BUCKET_SECONDS = 24 * 3600
_TIMELINE_YEAR_BUCKET_SECONDS = 7 * 24 * 3600
# 1970-01-05 00:00:00 UTC: the first Monday after the Unix epoch, the grid
# anchor for the Monday-anchored year-slice weeks.
_TIMELINE_YEAR_GRID_EPOCH_OFFSET = 4 * 24 * 3600
_TIMELINE_YEAR_LABEL_OFFSET_DAYS = 6
# One verified snapshot per resample bucket: the last row of the bucket,
# resolved with an index seek on ``timestamp`` instead of a full scan.
_TIMELINE_BUCKET_QUERY = (
    "SELECT profit_overall, funds_locked FROM upnl_history"
    " WHERE performance_verified = 1"
    " AND timestamp >= ? AND timestamp < ?"
    " ORDER BY timestamp DESC, id DESC LIMIT 1"
)


def _advance_timeline_generation() -> None:
    """Mark the uPNL snapshot data as changed for every cache holder."""
    global _timeline_generation
    _timeline_generation += 1


class Statistic:
    """Compute and persist trading statistics."""

    PROFIT_CACHE_TTL_SECONDS = 2

    def __init__(self, trades: Trades | None = None) -> None:
        """Initialize statistics with an injectable trade reader."""
        self.trades = trades or Trades()
        self.autopilot = Autopilot()
        self.capital_budget = CapitalBudgetService()
        self.snapshot_interval_seconds = 60
        self._snapshot_lock = asyncio.Lock()
        # (generation, expiry on the monotonic clock, cached point list).
        self._timeline_cache: tuple[int, float, list[dict[str, Any]]] | None = None
        self._timeline_cache_lock = asyncio.Lock()
        self.timeline_horizons = {
            "day": timedelta(days=1),
            "week": timedelta(days=7),
            "month": timedelta(days=30),
            "year": PROFIT_TIMELINE_HORIZON,
        }

    @staticmethod
    def _log_orm_error(message: str) -> None:
        """Log ORM failures with traceback while preserving caller fallbacks."""
        logging.error("%s", message, exc_info=True)

    @staticmethod
    def _extract_date_key(timestamp: Any) -> str | None:
        """Normalize timestamp-like values into a YYYY-MM-DD grouping key."""
        if isinstance(timestamp, datetime):
            return timestamp.date().isoformat()
        if isinstance(timestamp, str):
            normalized = timestamp.strip()
            if not normalized:
                return None
            try:
                return (
                    datetime.fromisoformat(normalized.replace("Z", "+00:00"))
                    .date()
                    .isoformat()
                )
            except ValueError:
                pass
            if len(normalized) >= 10:
                try:
                    return (
                        datetime.strptime(normalized[:10], "%Y-%m-%d")
                        .date()
                        .isoformat()
                    )
                except ValueError:
                    return None
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
        *,
        strict: bool = False,
    ) -> float:
        """Return a scalar SUM aggregate with a stable 0.0 fallback."""
        try:
            result = await queryset.annotate(total=Sum(field_name)).values_list(
                "total", flat=True
            )
            return float(result[0] or 0.0)
        except BaseORMException:
            self._log_orm_error(error_message)
            if strict:
                raise
            return 0.0

    async def _get_profit_rows_since(
        self,
        begin_datetime: datetime | Any,
        error_message: str,
        *,
        strict: bool = False,
    ) -> list[tuple[Any, Any]]:
        """Return closed-trade profit rows since the given date boundary."""
        try:
            return (
                await realized_closed_trades()
                .filter(close_date__gt=begin_datetime)
                .values_list("close_date", "profit")
            )
        except BaseORMException:
            self._log_orm_error(error_message)
            if strict:
                raise
            return []

    async def _get_open_trade_profit_snapshot(
        self, *, strict: bool = False
    ) -> tuple[float, float]:
        """Return open-trade upnl and funds-locked totals."""
        try:
            open_trade_rows = await model.OpenTrades.all().values(
                "profit",
                "cost",
                "lifecycle_mode",
                "accumulation_remaining_cost",
            )
            upnl_value = 0.0
            funds_locked = 0.0
            for row in open_trade_rows:
                accumulation = row.get("lifecycle_mode") == "accumulation"
                if not accumulation:
                    upnl_value += float(row.get("profit") or 0.0)
                committed_quote = float(
                    row.get("accumulation_remaining_cost" if accumulation else "cost")
                    or 0.0
                )
                funds_locked += max(0.0, committed_quote)
            return float(upnl_value), float(funds_locked)
        except BaseORMException as exc:
            logging.error("Error getting open-trade profit snapshot: %s", exc)
            if strict:
                raise
            return 0.0, 0.0

    async def _performance_complete(self, *, strict: bool = False) -> bool:
        """Do not label legacy DCA aggregates as complete accumulation returns."""
        try:
            return not (
                await model.AccumulationActivation.all().exists()
                or await model.OpenTrades.filter(lifecycle_mode="accumulation").exists()
            )
        except BaseORMException:
            logging.exception("Could not verify performance coverage.")
            if strict:
                raise
            return False

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
    def _stored_timestamp_literal(value: datetime) -> str:
        """Format a UTC instant exactly as it is stored in ``UpnlHistory``.

        Tortoise persists aware datetimes through ``isoformat()``, which
        omits the fractional seconds when the microsecond is zero. Query
        bounds must follow the same rule: with that rule, lexicographic
        order of the stored strings equals chronological order for every
        stored row (the ``+00:00`` terminator sorts before any
        ``.ffffff`` fractional continuation, which is chronologically
        correct because both denote the same or later instants).
        """
        if value.microsecond:
            return value.strftime("%Y-%m-%d %H:%M:%S.%f+00:00")
        return value.strftime("%Y-%m-%d %H:%M:%S+00:00")

    @staticmethod
    def _floor_to_bucket_grid(
        value: datetime, bucket_seconds: int, grid_epoch_offset: int
    ) -> datetime:
        """Floor ``value`` onto the bucket grid anchored at the epoch offset."""
        epoch = int(value.timestamp())
        floored = grid_epoch_offset + (
            (epoch - grid_epoch_offset) // bucket_seconds * bucket_seconds
        )
        return datetime.fromtimestamp(floored, tz=timezone.utc)

    async def _fetch_slice_timeline(
        self,
        slice_rank: int,
        slice_start: datetime,
        slice_end: datetime | None,
        generation_end: datetime,
        bucket_seconds: int,
        grid_epoch_offset: int,
        label_offset: timedelta,
        data_min: datetime,
        data_max: datetime,
        best: dict[str, tuple[int, float, float]],
    ) -> None:
        """Store the last snapshot of every bucket of one slice in ``best``.

        ``slice_rank`` breaks label collisions in favour of the newer slice
        (matching the original merge order), ``slice_end`` bounds the rows
        the slice may read (the day slice is unbounded), and
        ``generation_end`` stops the bucket grid - for the day slice it is
        one bucket past ``now`` so a snapshot written while the rebuild
        runs still lands in an emitted bucket.
        """
        connection = Tortoise.get_connection("default")
        step = timedelta(seconds=bucket_seconds)
        e = self._floor_to_bucket_grid(slice_start, bucket_seconds, grid_epoch_offset)
        while e < generation_end:
            upper = e + step
            if slice_end is not None:
                upper = min(upper, slice_end)
            if upper > data_min and e <= data_max:
                lower = max(e, slice_start)
                _, rows = await connection.execute_query(
                    _TIMELINE_BUCKET_QUERY,
                    [
                        self._stored_timestamp_literal(lower),
                        self._stored_timestamp_literal(upper),
                    ],
                )
                if rows:
                    profit, funds = rows[0]
                    label = (e + label_offset).strftime("%Y-%m-%d %H:%M:%S")
                    current = best.get(label)
                    if current is None or slice_rank >= current[0]:
                        best[label] = (slice_rank, float(profit), float(funds))
            e += step

    async def _fetch_profit_overall_timeline(
        self, now: datetime
    ) -> list[dict[str, Any]]:
        """Rebuild the profit timeline without scanning the full history.

        Every bucket of the adaptive grid (15min day, 4h week, 1d month,
        Monday-anchored 1w year) is resolved with a single ``LIMIT 1``
        index seek for its last verified snapshot - the exact value the
        original pandas ``resample(...).last()`` pipeline emitted for that
        bucket - so a cold rebuild reads a few hundred rows instead of a
        year of snapshots. The per-slice points are merged with
        later-slice precedence, mirroring the original
        ``concat``/``sort_index``/``dedup(keep="last")`` order, keeping the
        output point-for-point identical.
        """
        horizons = self.timeline_horizons
        day_start = now - horizons["day"]
        week_start = now - horizons["week"]
        month_start = now - horizons["month"]
        _, range_rows = await Tortoise.get_connection("default").execute_query(
            "SELECT MIN(timestamp), MAX(timestamp) FROM upnl_history"
            " WHERE performance_verified = 1"
        )
        data_min, data_max = range_rows[0]
        if data_max is None:
            return []
        data_min_dt = datetime.fromisoformat(data_min)
        data_max_dt = datetime.fromisoformat(data_max)
        best: dict[str, tuple[int, float, float]] = {}
        await self._fetch_slice_timeline(
            slice_rank=0,
            slice_start=now - horizons["year"],
            slice_end=month_start,
            generation_end=month_start,
            bucket_seconds=_TIMELINE_YEAR_BUCKET_SECONDS,
            grid_epoch_offset=_TIMELINE_YEAR_GRID_EPOCH_OFFSET,
            label_offset=timedelta(days=_TIMELINE_YEAR_LABEL_OFFSET_DAYS),
            data_min=data_min_dt,
            data_max=data_max_dt,
            best=best,
        )
        await self._fetch_slice_timeline(
            slice_rank=1,
            slice_start=month_start,
            slice_end=week_start,
            generation_end=week_start,
            bucket_seconds=_TIMELINE_MONTH_BUCKET_SECONDS,
            grid_epoch_offset=0,
            label_offset=timedelta(0),
            data_min=data_min_dt,
            data_max=data_max_dt,
            best=best,
        )
        await self._fetch_slice_timeline(
            slice_rank=2,
            slice_start=week_start,
            slice_end=day_start,
            generation_end=day_start,
            bucket_seconds=_TIMELINE_WEEK_BUCKET_SECONDS,
            grid_epoch_offset=0,
            label_offset=timedelta(0),
            data_min=data_min_dt,
            data_max=data_max_dt,
            best=best,
        )
        await self._fetch_slice_timeline(
            slice_rank=3,
            slice_start=day_start,
            slice_end=None,
            generation_end=now + timedelta(seconds=_TIMELINE_DAY_BUCKET_SECONDS),
            bucket_seconds=_TIMELINE_DAY_BUCKET_SECONDS,
            grid_epoch_offset=0,
            label_offset=timedelta(0),
            data_min=data_min_dt,
            data_max=data_max_dt,
            best=best,
        )
        return [
            {"timestamp": label, "profit_overall": profit, "funds_locked": funds}
            for label, (_, profit, funds) in sorted(best.items())
        ]

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
            native, _ = await self._accumulation_history(begin_datetime.isoformat())
            for day, value in native.items():
                if day >= begin_datetime.isoformat():
                    profit_data[day] = profit_data.get(day, 0.0) + value
            profit_data = await asyncio.to_thread(
                self._resample_profit_data_sync, profit_data, period
            )

        except BaseORMException as e:
            logging.error("Error getting profits for %s data: %s", period, e)

        return profit_data

    async def _accumulation_history(
        self, since: str | None = None
    ) -> tuple[dict[str, float], bool]:
        """Merge only a complete single-quote native execution history."""
        from service.runtime_services import get_active_accumulation_runtime

        runtime = get_active_accumulation_runtime()
        if runtime is None or not runtime.ready:
            return {}, await self._performance_complete()
        report = await runtime.performance()
        currency = str(runtime.adapter.config_provider().get("currency", "")).upper()
        from service.accumulation.performance import accumulated_daily_history

        history = (
            await accumulated_daily_history(since)
            if report.get("history_complete", False)
            else []
        )
        if not report.get("history_complete", False) or any(
            row["quote"] != currency for row in history
        ):
            return {}, False
        return {row["date"]: float(row["profit"]) for row in history}, True

    async def get_profit(self) -> dict[str, Any]:
        """Return profit, uPNL, and autopilot summaries."""
        return copy.deepcopy(await self._get_profit_cached())

    async def get_profit_for_dashboard(
        self, available_quote: float | None, *, force_refresh: bool = False
    ) -> dict[str, Any]:
        """Return profit data enriched for the dashboard websocket stream."""
        profit_data = copy.deepcopy(
            await (
                self._get_profit_base(strict=True)
                if force_refresh
                else self._get_profit_base_cached()
            )
        )
        await self._apply_autopilot_runtime_state(
            profit_data,
            available_quote=available_quote,
        )
        profit_data["funds_available"] = available_quote
        profit_data["funds_tradable"] = self._derive_tradable_quote(
            available_quote,
            profit_data,
        )
        return profit_data

    async def invalidate_profit_caches(self) -> None:
        """Invalidate DB-backed profit aggregates after bulk ledger replacement."""
        for cached_reader in (
            self._get_profit_base_cached,
            self._get_profit_cached,
        ):
            cache_clear = getattr(cached_reader, "cache_clear", None)
            if cache_clear is not None:
                await cache_clear()

    @helper.async_ttl_cache(maxsize=1, ttl=PROFIT_CACHE_TTL_SECONDS)
    async def _get_profit_base_cached(self) -> dict[str, Any]:
        """Compute and cache DB-backed profit aggregates."""
        return await self._get_profit_base()

    async def _get_profit_base(self, *, strict: bool = False) -> dict[str, Any]:
        """Compute DB-backed profit aggregates without reusing the cache."""
        profit_data = {}
        begin_week = (
            datetime.now() + timedelta(days=(0 - datetime.now().weekday()))
        ).date()

        open_trade_snapshot_task = self._get_open_trade_profit_snapshot(strict=strict)
        closed_profit_task = self._get_sum_value(
            realized_closed_trades(),
            "profit",
            "Error getting profit: %s",
            strict=strict,
        )
        profit_week_task = self._get_profit_rows_since(
            begin_week,
            "Error getting profits for the week: %s",
            strict=strict,
        )

        (
            open_trade_snapshot,
            closed_profit,
            profit_week_rows,
        ) = await asyncio.gather(
            open_trade_snapshot_task,
            closed_profit_task,
            profit_week_task,
        )
        upnl_value, funds_locked = open_trade_snapshot

        profit_data["performance_complete"] = await self._performance_complete(
            strict=strict
        )
        if not profit_data["performance_complete"]:
            from service.runtime_services import get_active_accumulation_runtime

            runtime = get_active_accumulation_runtime()
            if runtime is not None and runtime.ready:
                try:
                    report = await runtime.performance()
                    profit_data["accumulation_performance"] = report
                    currency = str(
                        runtime.adapter.config_provider().get("currency", "")
                    ).upper()
                    if report["complete"] and all(
                        group["quote"] == currency for group in report["by_quote"]
                    ):
                        upnl_value += sum(
                            float(group["unrealized"]) for group in report["by_quote"]
                        )
                        closed_profit += sum(
                            float(group["realized"]) for group in report["by_quote"]
                        )
                        profit_data["performance_complete"] = True
                except (ValueError, OSError, TimeoutError):
                    logging.warning(
                        "Accumulation valuation unavailable; retaining Dynamic DCA subtotals."
                    )
        manual_stop_incomplete = await has_unverified_manual_stop_profit()
        if manual_stop_incomplete:
            profit_data["performance_complete"] = False
        profit_data["performance_scope"] = (
            "incomplete"
            if manual_stop_incomplete
            else "all_trades"
            if profit_data["performance_complete"]
            else "dynamic_dca_only"
        )

        profit_data["upnl"] = upnl_value
        profit_data["profit_overall"] = closed_profit + float(
            profit_data["upnl"] or 0.0
        )
        profit_data["funds_locked"] = funds_locked
        profit_data["profit_week"] = self._group_profit_rows_by_date(profit_week_rows)
        try:
            native_history, history_complete = await self._accumulation_history(
                begin_week.isoformat()
            )
            for day, value in native_history.items():
                if day >= begin_week.isoformat():
                    profit_data["profit_week"][day] = (
                        profit_data["profit_week"].get(day, 0.0) + value
                    )
            profit_data["profit_history_scope"] = (
                "all_verified_executions" if history_complete else "dynamic_dca_only"
            )
            if manual_stop_incomplete:
                profit_data["profit_history_scope"] = "incomplete"
        except (ValueError, OSError, TimeoutError):
            profit_data["profit_history_scope"] = "dynamic_dca_only"
        profit_data["profit_overall_timestamp"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        await self._store_upnl_snapshot(profit_data)
        return profit_data

    async def _apply_autopilot_runtime_state(
        self,
        profit_data: dict[str, Any],
        *,
        available_quote: float | None | object = AVAILABLE_QUOTE_UNSET,
    ) -> None:
        """Attach current Autopilot/Green Phase state to profit payloads."""
        config = await Config.instance()
        config_snapshot = config.snapshot()
        autopilot_state = await self.autopilot.resolve_runtime_state(
            funds_locked=float(profit_data.get("funds_locked") or 0.0),
            config=config_snapshot,
            available_quote=available_quote,
        )
        capital_state = await self.capital_budget.get_runtime_state(config_snapshot)
        profit_data.update(capital_state)
        profit_data["autopilot"] = autopilot_state["mode"]
        profit_data["autopilot_effective_max_bots"] = autopilot_state[
            "effective_max_bots"
        ]
        profit_data["autopilot_green_phase_detected"] = autopilot_state[
            "green_phase_detected"
        ]
        profit_data["autopilot_green_phase_active"] = autopilot_state[
            "green_phase_active"
        ]
        profit_data["autopilot_green_phase_extra_deals"] = autopilot_state[
            "green_phase_extra_deals"
        ]
        profit_data["autopilot_green_phase_strength"] = autopilot_state[
            "green_phase_strength"
        ]
        profit_data["autopilot_green_phase_block_reason"] = autopilot_state[
            "green_phase_block_reason"
        ]
        profit_data["autopilot_green_phase_ramp_ready"] = autopilot_state[
            "green_phase_ramp_ready"
        ]
        profit_data["autopilot_memory_status"] = autopilot_state.get("memory_status")
        profit_data["autopilot_memory_stale"] = bool(
            autopilot_state.get("memory_stale")
        )
        profit_data["autopilot_memory_stale_reason"] = autopilot_state.get(
            "memory_stale_reason"
        )
        profit_data["autopilot_memory_current_closes"] = int(
            autopilot_state.get("memory_current_closes") or 0
        )
        profit_data["autopilot_memory_required_closes"] = int(
            autopilot_state.get("memory_required_closes") or 0
        )
        profit_data["autopilot_memory_featured_symbol"] = autopilot_state.get(
            "memory_featured_symbol"
        )

    @staticmethod
    def _to_optional_float(value: Any) -> float | None:
        """Return a finite float or None for unavailable values."""
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if pd.notna(parsed) else None

    @classmethod
    def _derive_tradable_quote(
        cls,
        available_quote: float | None,
        profit_data: dict[str, Any],
    ) -> float | None:
        """Return exchange-free funds constrained by the global capital budget."""
        exchange_available = cls._to_optional_float(available_quote)
        if exchange_available is None:
            return None

        if profit_data.get("capital_budget_reason") == "capital_budget_unconfigured":
            return round(max(0.0, exchange_available), 8)

        capital_available = cls._to_optional_float(
            profit_data.get("capital_available_quote")
        )
        if capital_available is None:
            return 0.0

        return round(
            min(max(0.0, exchange_available), max(0.0, capital_available)),
            8,
        )

    @helper.async_ttl_cache(maxsize=1, ttl=PROFIT_CACHE_TTL_SECONDS)
    async def _get_profit_cached(self) -> dict[str, Any]:
        """Compute and cache profit, uPNL, and autopilot summaries."""
        profit_data = copy.deepcopy(await self._get_profit_base_cached())
        await self._apply_autopilot_runtime_state(profit_data)
        return profit_data

    async def _store_upnl_snapshot(self, profit_data: dict[str, Any]) -> None:
        """Persist a sampled uPNL snapshot for long-term charting."""
        if profit_data.get("performance_complete") is False:
            return
        async with self._snapshot_lock:
            await self._store_upnl_snapshot_locked(profit_data)

    async def _store_upnl_snapshot_locked(self, profit_data: dict[str, Any]) -> None:
        """Check and write one sample while the single-instance lock is held."""
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
            # The new snapshot is the freshest timeline input; advance the
            # shared generation so every cached resample (this instance or
            # another Statistic's) is dropped until rebuilt.
            self.invalidate_timeline_cache()
            _advance_timeline_generation()
        except BaseORMException as e:
            # Broad catch to avoid stats persistence failures affecting websocket data.
            logging.error("Error storing uPNL snapshot: %s", e)

    async def get_upnl_history_all(self) -> list[dict[str, Any]]:
        """Return overall profit snapshots from the beginning, ordered by timestamp."""
        upnl_data: list[dict[str, Any]] = []
        try:
            rows = (
                await model.UpnlHistory.filter(performance_verified=True)
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

    def invalidate_timeline_cache(self) -> None:
        """Drop this instance's cached timeline so the next fetch re-resamples."""
        self._timeline_cache = None

    @staticmethod
    def _timeline_cache_valid(
        entry: tuple[int, float, list[dict[str, Any]]] | None,
    ) -> bool:
        """Whether a cached entry still matches the current data generation."""
        return (
            entry is not None
            and entry[0] == _timeline_generation
            and time.monotonic() < entry[1]
        )

    async def get_profit_overall_timeline(self) -> list[dict[str, Any]]:
        """Return last-12-month timeline with multi-resolution buckets.

        Resolution windows:
        - day: 15min
        - week: 4h
        - month: 1d
        - year: 1w

        Each rebuild resolves one snapshot per resample bucket with
        indexed ``LIMIT 1`` seeks (``_fetch_profit_overall_timeline``), so
        a cold rebuild stays in the tens of milliseconds even for a full
        year of snapshots. The result is cached for
        ``TIMELINE_CACHE_TTL_SECONDS`` and invalidated when any Statistic
        instance stores a new snapshot or old history is pruned, so
        concurrent dashboard clients share one rebuild per window. The
        cached value is treated as immutable; callers receive a copy of
        the point list.
        """
        cached = self._timeline_cache
        if self._timeline_cache_valid(cached):
            return list(cached[2])
        async with self._timeline_cache_lock:
            cached = self._timeline_cache
            if self._timeline_cache_valid(cached):
                return list(cached[2])
            now = datetime.now(timezone.utc)
            try:
                timeline = await self._fetch_profit_overall_timeline(now)
            except BaseORMException as e:
                # Broad catch to keep stats endpoints responsive. Errors are
                # not cached, so a healthy follow-up fetch re-queries.
                logging.error("Error getting profit-overall timeline: %s", e)
                return []
            self._timeline_cache = (
                _timeline_generation,
                time.monotonic() + TIMELINE_CACHE_TTL_SECONDS,
                timeline,
            )
            return list(timeline)

    async def update_statistic_data(self, stats: dict[str, Any]) -> None:
        """Update open trade statistics based on recent ticker data."""
        if stats["type"] == "waiting_check":
            logging.trace("%s", stats)
            return

        if stats["type"] != "dca_check":
            profit = (
                stats["current_price"] * stats["total_amount"] - stats["total_cost"]
            )
            open_timestamp = datetime.timestamp(datetime.now()) * 1000
            has_base_order_timestamp = False

            base_order = await self.trades.get_trade_by_ordertype(
                stats["symbol"], baseorder=True
            )

            try:
                if base_order and base_order[0].get("timestamp") is not None:
                    open_timestamp = float(base_order[0]["timestamp"])
                    has_base_order_timestamp = True
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

            open_trade_rows = await self.trades.get_open_trades_by_symbol(
                stats["symbol"]
            )
            open_trade = open_trade_rows[0] if open_trade_rows else {}
            open_date_value = format_trade_datetime(
                trade_datetime_from_ms(float(open_timestamp))
            )
            preserved_open_date = str(open_trade.get("open_date") or "").strip()
            if preserved_open_date and not has_base_order_timestamp:
                open_date_value = preserved_open_date

            # Update open trade statistics
            payload = {
                "profit": profit,
                "profit_percent": stats["actual_pnl"],
                "amount": stats["total_amount"],
                "cost": stats["total_cost"],
                "current_price": stats["current_price"],
                "tp_price": stats["tp_price"],
                "avg_price": stats["avg_price"],
                "open_date": open_date_value,
            }
            await self.trades.update_open_trades(payload, stats["symbol"])
