"""Periodic cleanup tasks for stale ticker data."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import helper
import model
from service.config import Config
from service.data import Data
from service.database import optimize_sqlite_connection, run_sqlite_write_with_retry
from service.trades import Trades

logging = helper.LoggerFactory.get_logger("logs/housekeeper.log", "housekeeper")


class Housekeeper:
    """Cleanup service for old ticker entries."""

    UPNL_RETENTION_DAYS_DEFAULT = 0

    def __init__(self) -> None:
        self.config = None

        # Class variables
        Housekeeper.status = True

    async def init(self) -> None:
        """Initialize the housekeeper with current configuration."""
        config = await Config.instance()
        config.subscribe(self.on_config_change)
        self.on_config_change(config._cache)

    def on_config_change(self, config: dict[str, Any]) -> None:
        """Reload housekeeping configuration."""
        logging.info("Reload housekeeper")
        self.config = config

    def _get_housekeeping_interval_days(self) -> int:
        """Return housekeeping interval in days with safe defaults."""
        try:
            interval_days = int(self.config.get("housekeeping_interval", 2))
        except (TypeError, ValueError):
            return 2
        return max(1, interval_days)

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
        while Housekeeper.status:
            if self.config:
                interval_days = self._get_housekeeping_interval_days()
                actual_timestamp = datetime.now()
                cleanup_timestamp = actual_timestamp - timedelta(days=interval_days)
                try:
                    active_symbols = await Trades().get_symbols()
                    ticker_symbols = await Data().get_ticker_symbol_list()
                    # Do not housekeep active trades
                    for symbol in ticker_symbols:
                        if symbol not in active_symbols:
                            query = await run_sqlite_write_with_retry(
                                lambda: model.Tickers.filter(
                                    timestamp__lt=cleanup_timestamp.timestamp()
                                ).delete(),
                                "housekeeping ticker cleanup",
                            )
                            logging.info(
                                f"Start housekeeping. Delete {query} entries older then {cleanup_timestamp}"
                            )
                    await self._cleanup_upnl_history(actual_timestamp)
                    await optimize_sqlite_connection()
                except Exception as e:
                    # Broad catch to keep the housekeeping loop running.
                    logging.error(f"Error db housekeeping: {e}")

                await asyncio.sleep(interval_days * 24 * 60 * 60)
            else:
                await asyncio.sleep(5)

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
        Housekeeper.status = False
