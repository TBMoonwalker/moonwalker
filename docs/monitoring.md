# Monitoring Documentation

## Overview
Moonwalker monitoring sends Telegram messages for executed trades:
- `trade.buy`
- `trade.sell`

The implementation uses [Telethon](https://docs.telethon.dev/en/stable/).

## Configuration Keys
Configure these keys in the Control Center's `Operator alerts` section or via
API:

| Key | Type | Required | Description |
| --- | --- | --- | --- |
| `monitoring_enabled` | `bool` | yes | Enables trade notifications for buy/sell executions. |
| `monitoring_telegram_api_id` | `int` | yes | Telegram API ID from [my.telegram.org](https://my.telegram.org). |
| `monitoring_telegram_api_hash` | `string` | yes | Telegram API hash from [my.telegram.org](https://my.telegram.org). |
| `monitoring_telegram_bot_token` | `string` | yes | Bot token from BotFather. |
| `monitoring_telegram_chat_id` | `string` | yes | Target chat/channel/user id (e.g. `123456789`, `-100...`, `@channel_name`). |
| `monitoring_timeout_sec` | `int` | no | Send timeout per attempt. Default: `5`. |
| `monitoring_retry_count` | `int` | no | Retry attempts after a failed send. Default: `1`. |

Notes:
- `monitoring_timeout_sec` is clamped to a minimum of `1`.
- `monitoring_retry_count` is clamped to a minimum of `0`.

## How Notifications Are Triggered
1. A buy or sell order is executed.
2. Moonwalker calls the monitoring service with the event payload.
3. If `monitoring_enabled` is `true`, a Telegram message is sent.

No extra filters are applied for notional size or dry-run mode.

## Telegram Message Format
Messages are sent in HTML parse mode for readability and include:
- Event title (`Moonwalker trade.buy` / `Moonwalker trade.sell`)
- Exchange
- Symbol
- Side
- Dry-run status
- Full payload in a formatted `<pre>` block

All dynamic values are escaped before sending.

## Test Telegram From UI
Use **Control Center -> Setup or Advanced -> Operator alerts -> Test Telegram**.

Behavior:
- Endpoint: `POST /monitoring/test`
- Sends a test Telegram message immediately.
- Works even when `monitoring_enabled` is `false`.
- Returns HTTP `200` on success, `400` on validation/send failure.

## Valid `monitoring_telegram_chat_id` Inputs
Moonwalker normalizes several Telethon-compatible target formats:
- Numeric IDs (`123456789`, `-1001234567890`)
- Username (`@my_channel`)
- Telegram URL (`https://t.me/my_channel`)

## Failure and Retry Behavior
- Missing required Telegram credentials causes the send attempt to fail.
- On send errors, Moonwalker retries based on `monitoring_retry_count`.
- Monitoring errors are logged to `logs/monitoring.log`.

## Monitoring Page Logs
The Monitoring page also exposes a read-only live log viewer for selected
allowlisted backend log files.

Behavior:
- Endpoint list: `GET /monitoring/logs`
- Endpoint batches: `GET /monitoring/logs/{source}`
- Transport: polling over HTTP, not WebSocket
- The UI polls for newer complete lines and can request older lines when you
  scroll to the top of the log panel.

Supported query parameters for `GET /monitoring/logs/{source}`:
- `limit`: max lines to return per request, capped server-side
- `cursor`: fetch newer complete lines after the previous cursor
- `before`: fetch older lines before the current oldest cursor

Notes:
- Only allowlisted sources are exposed to the frontend.
- Missing log files return an empty payload with `available: false`.
- If a log file rotates or truncates while the page is open, the response sets
  `rotated: true` so the UI can reset to the latest available lines.
- The selected current log file can be downloaded from the Monitoring page
  through `GET /monitoring/logs/{source}/download`.

## Example API Payload (Test)
```json
{
  "monitoring_telegram_api_id": 1234567,
  "monitoring_telegram_api_hash": "0123456789abcdef0123456789abcdef",
  "monitoring_telegram_bot_token": "123456:ABCDEF...",
  "monitoring_telegram_chat_id": "-1001234567890",
  "monitoring_timeout_sec": 5,
  "monitoring_retry_count": 1
}
```
