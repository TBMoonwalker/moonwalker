"""CSV-sourced signal plugin implementation."""

import ast
import asyncio
import json
import re
from pathlib import Path
from typing import Any

import helper
import model
from service.config import resolve_history_lookback_days, resolve_timeframe
from service.csv_signal_import import CSVSignalImportService
from service.data import Data

logging = helper.LoggerFactory.get_logger("logs/signal.log", "csv_signal")


class SignalPlugin:
    """Signal plugin that seeds open trades from a CSV source."""

    IDLE_INTERVAL_SECONDS = 60
    RETRY_INTERVAL_SECONDS = 30

    def __init__(self, watcher_queue: asyncio.Queue[Any]):
        self.config: dict[str, Any] = {}
        self.status = True
        self.watcher_queue = watcher_queue
        self.import_service = CSVSignalImportService()
        self.data = Data(persist_exchange=True)
        self._import_finished = False

    @staticmethod
    def _parse_signal_settings(raw_value: Any) -> dict[str, Any]:
        """Parse signal_settings payload from config."""
        if isinstance(raw_value, dict):
            return raw_value
        if raw_value is None:
            return {}

        raw_text = str(raw_value).strip()
        if not raw_text:
            return {}

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = ast.literal_eval(raw_text)

        if not isinstance(parsed, dict):
            raise TypeError("signal_settings must be a dictionary payload")

        return parsed

    async def _load_csv_content(self, source: str) -> str:
        """Load CSV content from URL, filesystem path, or inline payload."""
        normalized_source = source.strip()
        if not normalized_source:
            raise ValueError("Missing CSV source in signal_settings.csv_source")

        # Allow direct inline CSV payload.
        if "\n" in normalized_source and ";" in normalized_source:
            return normalized_source

        if normalized_source.startswith(("http://", "https://")):
            try:
                import httpx
            except ImportError as exc:
                raise ValueError(
                    "httpx is required for URL-based CSV source loading."
                ) from exc
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(normalized_source)
                response.raise_for_status()
                return response.text

        path = Path(normalized_source).expanduser()
        if not path.exists() or not path.is_file():
            raise ValueError(f"CSV source file not found: {normalized_source}")

        return await asyncio.to_thread(path.read_text, encoding="utf-8-sig")

    @staticmethod
    def _timeframe_to_milliseconds(timeframe: str) -> int:
        """Convert timeframe notation to milliseconds."""
        normalized = str(timeframe or "").strip().lower()
        if not normalized:
            return 60_000

        normalized = normalized.replace("min", "m")
        match = re.fullmatch(r"(\d+)\s*([mhdw])", normalized)
        if not match:
            return 60_000

        value = max(1, int(match.group(1)))
        unit = match.group(2)
        multipliers = {
            "m": 60_000,
            "h": 3_600_000,
            "d": 86_400_000,
            "w": 604_800_000,
        }
        return value * multipliers[unit]

    async def _import_once(self) -> bool:
        """Import trades once and return True when no further retries are needed."""
        open_trade_count = await model.OpenTrades.all().count()
        if open_trade_count > 0:
            logging.info(
                "Skipping csv_signal import: %s open trades already exist.",
                open_trade_count,
            )
            return True

        settings = self._parse_signal_settings(self.config.get("signal_settings"))
        csv_source = settings.get("csv_source")
        if not csv_source or str(csv_source).strip().lower() in {
            "",
            "false",
            "none",
            "null",
        }:
            raise ValueError(
                "Missing signal_settings.csv_source for csv_signal plugin."
            )

        csv_content = await self._load_csv_content(str(csv_source))
        quote_currency = str(self.config.get("currency", "USDT")).upper().strip()
        parsed_rows = self.import_service._parse_csv_rows(csv_content, quote_currency)
        symbols = sorted(parsed_rows.keys())
        history_data = resolve_history_lookback_days(
            self.config,
            timeframe=resolve_timeframe(self.config),
        )
        candle_ms = self._timeframe_to_milliseconds(resolve_timeframe(self.config))
        for symbol in symbols:
            entries = sorted(
                parsed_rows.get(symbol, []), key=lambda row: row["timestamp"]
            )
            first_timestamp = int(entries[0]["timestamp"]) if entries else None
            if first_timestamp is None:
                raise RuntimeError(
                    f"Missing base-order timestamp for history prefill of {symbol}."
                )
            since_ms = max(0, int(first_timestamp) - candle_ms)
            logging.info(
                "Prefilling history for %s from %s (first buy %s, timeframe %s).",
                symbol,
                since_ms,
                first_timestamp,
                resolve_timeframe(self.config),
            )
            success = await self.data.add_history_data_for_symbol(
                symbol=symbol,
                history_data=history_data,
                config=self.config,
                since_ms=since_ms,
            )
            if not success:
                raise RuntimeError(
                    f"History prefill failed for {symbol} in csv_signal plugin."
                )

        take_profit = float(self.config.get("tp", 0.0) or 0.0)
        result = await self.import_service.import_from_csv(
            csv_content=csv_content,
            quote_currency=quote_currency,
            take_profit=take_profit,
            bot_name="csv_signal",
        )
        symbols = result.get("symbols", [])
        if symbols:
            await self.watcher_queue.put(symbols)

        logging.info(
            "csv_signal import completed: symbols=%s rows=%s",
            result.get("symbol_count", 0),
            result.get("row_count", 0),
        )
        return True

    async def run(self, config: dict[str, Any]) -> None:
        """Try import and keep plugin task alive for runtime config reloads."""
        self.config = config
        while self.status:
            if not self._import_finished:
                try:
                    self._import_finished = await self._import_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - Keep retrying on failures.
                    logging.error("csv_signal import attempt failed: %s", exc)
                    await asyncio.sleep(self.RETRY_INTERVAL_SECONDS)
                    continue

            await asyncio.sleep(self.IDLE_INTERVAL_SECONDS)

    async def shutdown(self) -> None:
        """Signal plugin loop to stop."""
        self.status = False
        await self.data.close()
