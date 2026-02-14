"""Trade monitoring and outbound messaging helpers."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from urllib import request

import helper
from telethon import TelegramClient
from telethon.sessions import MemorySession

logging = helper.LoggerFactory.get_logger("logs/monitoring.log", "monitoring")


class MonitoringService:
    """Send trade execution events to configured monitoring channels."""

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
        """Send a monitoring test message regardless of monitoring_enabled."""
        success = await self._send_message(
            "monitoring.test",
            {"message": "Moonwalker monitoring channel test"},
            config,
        )
        if not success:
            return False, "Monitoring channel test failed."
        return True, "Monitoring channel test sent."

    async def _send_message(
        self, event_type: str, payload: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Send a monitoring message and return success state."""

        channel = str(config.get("monitoring_channel", "webhook") or "webhook").lower()
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

        message = self._build_trade_message(event_type, payload, config)

        send_operation = None
        if channel == "webhook":
            webhook_url = str(config.get("monitoring_webhook_url", "") or "").strip()
            if not webhook_url:
                logging.warning(
                    "Monitoring is enabled but 'monitoring_webhook_url' is empty."
                )
                return False

            async def _send() -> None:
                await asyncio.to_thread(
                    self._post_webhook,
                    webhook_url,
                    message,
                    timeout_seconds,
                )

            send_operation = _send
        elif channel == "telegram":
            api_id = self._safe_int(config.get("monitoring_telegram_api_id"), 0)
            api_hash = str(config.get("monitoring_telegram_api_hash", "") or "").strip()
            bot_token = str(
                config.get("monitoring_telegram_bot_token", "") or ""
            ).strip()
            chat_id = str(config.get("monitoring_telegram_chat_id", "") or "").strip()
            if api_id <= 0 or not api_hash or not bot_token or not chat_id:
                logging.warning(
                    "Monitoring telegram channel requires api_id, api_hash, "
                    "bot token and chat id."
                )
                return False

            telegram_text = self._build_telegram_text(event_type, payload, config)

            async def _send() -> None:
                await self._send_telegram(
                    api_id,
                    api_hash,
                    bot_token,
                    chat_id,
                    telegram_text,
                )

            send_operation = _send
        else:
            logging.warning("Unsupported monitoring channel '%s'.", channel)
            return False

        for attempt in range(retry_count + 1):
            try:
                await asyncio.wait_for(send_operation(), timeout=timeout_seconds)
                return True
            except Exception as exc:  # noqa: BLE001 - Monitoring must never crash flow.
                logging.error(
                    "Monitoring %s failed (attempt %s/%s): %s",
                    channel,
                    attempt + 1,
                    retry_count + 1,
                    exc,
                )
        return False

    def _build_trade_message(
        self, event_type: str, payload: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a normalized monitoring payload."""
        now = datetime.now(tz=timezone.utc).isoformat()
        return {
            "event": event_type,
            "timestamp": now,
            "exchange": config.get("exchange"),
            "dry_run": bool(config.get("dry_run", True)),
            "trade": payload,
        }

    def _post_webhook(
        self, webhook_url: str, message: dict[str, Any], timeout_seconds: int
    ) -> None:
        """Send a single JSON POST request to the webhook endpoint."""
        body = json.dumps(message).encode("utf-8")
        req = request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=timeout_seconds) as response:
            status_code = int(response.getcode())
            if status_code >= 400:
                raise RuntimeError(f"Webhook returned status {status_code}")

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
        async with TelegramClient(MemorySession(), api_id, api_hash) as client:
            await client.start(bot_token=bot_token)
            await client.send_message(entity=entity, message=text)

    def _build_telegram_text(
        self, event_type: str, payload: dict[str, Any], config: dict[str, Any]
    ) -> str:
        """Build a compact human-readable Telegram message."""
        symbol = payload.get("symbol", "-")
        side = payload.get("side", "-")
        exchange = config.get("exchange", "-")
        dry_run = bool(config.get("dry_run", True))
        details = json.dumps(payload, default=str)
        return (
            f"Moonwalker {event_type}\n"
            f"Exchange: {exchange}\n"
            f"Symbol: {symbol}\n"
            f"Side: {side}\n"
            f"Dry-run: {dry_run}\n"
            f"Details: {details}"
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
