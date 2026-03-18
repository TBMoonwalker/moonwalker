"""Trade monitoring and outbound messaging helpers."""

import asyncio
import html
import json
from typing import Any

import helper
from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.sessions import MemorySession

logging = helper.LoggerFactory.get_logger("logs/monitoring.log", "monitoring")
MONITORING_SEND_EXCEPTIONS = (
    asyncio.TimeoutError,
    OSError,
    RPCError,
    RuntimeError,
    TypeError,
    ValueError,
)


class MonitoringService:
    """Send trade execution events to Telegram."""

    DEFAULT_TIMEOUT_SECONDS = 5
    DEFAULT_RETRY_COUNT = 1

    async def notify_trade(
        self, event_type: str, payload: dict[str, Any], config: dict[str, Any]
    ) -> None:
        """Send a trade notification when monitoring is enabled."""
        if not bool(config.get("monitoring_enabled", False)):
            return

        await self._send_message(event_type, payload, config)

    async def send_test_notification(self, config: dict[str, Any]) -> tuple[bool, str]:
        """Send a Telegram test message regardless of monitoring_enabled."""
        success = await self._send_message(
            "monitoring.test",
            {"message": "Moonwalker Telegram monitoring test"},
            config,
        )
        if not success:
            return False, "Monitoring Telegram test failed."
        return True, "Monitoring Telegram test sent."

    async def _send_message(
        self, event_type: str, payload: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Send a Telegram monitoring message and return success state."""
        timeout_seconds = self._safe_int(
            config.get("monitoring_timeout_sec", self.DEFAULT_TIMEOUT_SECONDS),
            self.DEFAULT_TIMEOUT_SECONDS,
            min_value=1,
        )
        retry_count = self._safe_int(
            config.get("monitoring_retry_count", self.DEFAULT_RETRY_COUNT),
            self.DEFAULT_RETRY_COUNT,
            min_value=0,
        )

        api_id = self._safe_int(
            config.get("api_id", config.get("monitoring_telegram_api_id")),
            0,
        )
        api_hash = str(
            config.get("api_hash", config.get("monitoring_telegram_api_hash", "")) or ""
        ).strip()
        bot_token = str(
            config.get("bot_token", config.get("monitoring_telegram_bot_token", ""))
            or ""
        ).strip()
        chat_id = str(
            config.get("chat_id", config.get("monitoring_telegram_chat_id", "")) or ""
        ).strip()
        if api_id <= 0 or not api_hash or not bot_token or not chat_id:
            logging.warning(
                "Monitoring telegram requires api_id, api_hash, bot token and chat id."
            )
            return False

        telegram_text = self._build_telegram_text(event_type, payload, config)

        for attempt in range(retry_count + 1):
            try:
                await asyncio.wait_for(
                    self._send_telegram(
                        api_id,
                        api_hash,
                        bot_token,
                        chat_id,
                        telegram_text,
                    ),
                    timeout=timeout_seconds,
                )
                return True
            except MONITORING_SEND_EXCEPTIONS as exc:
                logging.error(
                    "Monitoring telegram failed (attempt %s/%s): %s",
                    attempt + 1,
                    retry_count + 1,
                    exc,
                )
        return False

    async def _send_telegram(
        self,
        api_id: int,
        api_hash: str,
        bot_token: str,
        chat_id: str,
        text: str,
    ) -> None:
        """Send a Telegram message with Telethon."""
        entity = self._resolve_telegram_entity(chat_id)
        bot = TelegramClient(MemorySession(), api_id, api_hash)
        await bot.start(bot_token=bot_token)
        try:
            await bot.send_message(entity=entity, message=text, parse_mode="html")
        finally:
            await bot.disconnect()

    def _build_telegram_text(
        self, event_type: str, payload: dict[str, Any], config: dict[str, Any]
    ) -> str:
        """Build an HTML-formatted Telegram message."""
        symbol = html.escape(str(payload.get("symbol", "-")))
        side = html.escape(str(payload.get("side", "-")))
        exchange = html.escape(str(config.get("exchange", "-")))
        dry_run = bool(config.get("dry_run", True))
        event = html.escape(str(event_type))
        details = html.escape(json.dumps(payload, default=str, indent=2))
        status = "yes" if dry_run else "no"
        return (
            f"<b>Moonwalker {event}</b>\n"
            f"<b>Exchange:</b> {exchange}\n"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Side:</b> {side}\n"
            f"<b>Dry-run:</b> {status}\n\n"
            f"<b>Details</b>\n"
            f"<pre>{details}</pre>"
        )

    def _resolve_telegram_entity(self, chat_id: str) -> int | str:
        """Normalize Telegram target for Telethon send_message(entity=...)."""
        normalized = str(chat_id or "").strip()
        if not normalized:
            raise ValueError("Telegram chat id is empty.")

        if normalized.startswith("@"):
            return normalized
        if normalized.startswith("https://t.me/"):
            return normalized
        if normalized.lstrip("-").isdigit():
            return int(normalized)
        return normalized

    def _safe_int(self, value: Any, default: int, min_value: int = 0) -> int:
        """Parse int with fallback and lower bound."""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(min_value, parsed)
