"""Periodic cleanup tasks for stale ticker data."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import helper
import model
from service.config import Config, resolve_history_lookback_days, resolve_timeframe
from service.data import Data
from service.database import optimize_sqlite_connection, run_sqlite_write_with_retry
from service.trades import Trades

logging = helper.LoggerFactory.get_logger("logs/housekeeper.log", "housekeeper")


class Housekeeper:
    """Cleanup service for old ticker entries."""

    CLEANUP_LOOP_INTERVAL_SECONDS = 24 * 60 * 60
    UPNL_RETENTION_DAYS_DEFAULT = 0

    def __init__(self) -> None:
        self.config = None
        self._running = True

    async def init(self) -> None:
        """Initialize the housekeeper with current configuration."""
        config = await Config.instance()
        config.subscribe(self.on_config_change)
        self.on_config_change(config.snapshot())

    def on_config_change(self, config: dict[str, Any]) -> None:
        """Reload housekeeping configuration."""
        logging.info("Reload housekeeper")
        self.config = config

    def _get_ticker_retention_days(self) -> int:
        """Return ticker retention window in days based on history lookback."""
        timeframe = resolve_timeframe(self.config)
        return max(1, resolve_history_lookback_days(self.config, timeframe=timeframe))

    def _get_upnl_retention_days(self) -> int:
        """Return uPNL retention in days.

        A value of 0 means infinite retention (do not delete history).
        """
        try:
            retention_days = int(
                self.config.get(
                    "upnl_housekeeping_interval", self.UPNL_RETENTION_DAYS_DEFAULT
                )
            )
        except (TypeError, ValueError):
            return self.UPNL_RETENTION_DAYS_DEFAULT
        return max(0, retention_days)

    async def cleanup_ticker_database(self) -> None:
        """Remove old ticker data for inactive symbols."""
        while self._running:
            if self.config:
                retention_days = self._get_ticker_retention_days()
                actual_timestamp = datetime.now()
                try:
                    await self._cleanup_inactive_ticker_history(
                        actual_timestamp, retention_days
                    )
                    await self._cleanup_upnl_history(actual_timestamp)
                    await optimize_sqlite_connection()
                except Exception as e:
                    # Broad catch to keep the housekeeping loop running.
                    logging.error("Error db housekeeping: %s", e)

                await asyncio.sleep(self.CLEANUP_LOOP_INTERVAL_SECONDS)
            else:
                await asyncio.sleep(5)

    async def _cleanup_inactive_ticker_history(
        self, actual_timestamp: datetime, retention_days: int
    ) -> int:
        """Delete expired ticker rows only for symbols without active trades."""
        cleanup_timestamp = actual_timestamp - timedelta(days=retention_days)
        active_symbols = set(await Trades().get_symbols())
        ticker_symbols = set(await Data().get_ticker_symbol_list())
        inactive_symbols = sorted(ticker_symbols - active_symbols)

        if not inactive_symbols:
            return 0

        deleted = await run_sqlite_write_with_retry(
            lambda: model.Tickers.filter(
                symbol__in=inactive_symbols,
                timestamp__lt=cleanup_timestamp.timestamp(),
            ).delete(),
            "housekeeping ticker cleanup",
        )
        logging.info(
            "Housekeeping deleted %s ticker entries older than %s for %s inactive symbols "
            "(retention_days=%s)",
            deleted,
            cleanup_timestamp,
            len(inactive_symbols),
            retention_days,
        )
        return int(deleted or 0)

    async def _cleanup_upnl_history(self, actual_timestamp: datetime) -> None:
        """Remove old uPNL snapshots based on retention policy."""
        retention_days = self._get_upnl_retention_days()
        if retention_days == 0:
            return

        retention_timestamp = actual_timestamp - timedelta(days=retention_days)
        deleted = await run_sqlite_write_with_retry(
            lambda: model.UpnlHistory.filter(
                timestamp__lt=retention_timestamp
            ).delete(),
            "cleanup upnl history",
        )
        if deleted:
            logging.info(
                "Deleted %s uPNL history entries older than %s",
                deleted,
                retention_timestamp,
            )

    async def shutdown(self) -> None:
        """Stop housekeeping loop."""
        self._running = False
