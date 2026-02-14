"""Trade monitoring and outbound messaging helpers."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from urllib import request

import helper

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
        """Send a webhook test message regardless of monitoring_enabled."""
        success = await self._send_message(
            "monitoring.test",
            {"message": "Moonwalker monitoring webhook test"},
            config,
        )
        if not success:
            return False, "Monitoring webhook test failed."
        return True, "Monitoring webhook test sent."

    async def _send_message(
        self, event_type: str, payload: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Send a monitoring message and return success state."""

        channel = str(config.get("monitoring_channel", "webhook") or "webhook").lower()
        if channel != "webhook":
            logging.warning("Unsupported monitoring channel '%s'.", channel)
            return False

        webhook_url = str(config.get("monitoring_webhook_url", "") or "").strip()
        if not webhook_url:
            logging.warning(
                "Monitoring is enabled but 'monitoring_webhook_url' is empty."
            )
            return False

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
        for attempt in range(retry_count + 1):
            try:
                await asyncio.to_thread(
                    self._post_webhook,
                    webhook_url,
                    message,
                    timeout_seconds,
                )
                return True
            except Exception as exc:  # noqa: BLE001 - Monitoring must never crash flow.
                logging.error(
                    "Monitoring webhook failed (attempt %s/%s): %s",
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

    def _safe_int(self, value: Any, default: int, min_value: int = 0) -> int:
        """Parse int with fallback and lower bound."""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(min_value, parsed)
