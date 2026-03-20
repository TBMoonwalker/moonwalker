# API Reference

Moonwalker serves the Vue dashboard from the backend and exposes a small set of
REST and WebSocket endpoints that the UI uses directly.

The API is designed for a single Moonwalker instance with one shared trading
runtime and multiple concurrent dashboard clients.

## Frontend / Static Assets

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Serve the Vue SPA entrypoint. |
| `GET` | `/{path}` | Serve SPA routes with static-file fallback. |
| `GET` | `/static/{file_path}` | Serve built frontend assets. |

## Configuration

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/config/all` | Return the full config snapshot used by the dashboard. |
| `GET` | `/config/freshness` | Return the latest persisted config `updated_at` timestamp so dashboard clients can detect stale local snapshots. |
| `GET` | `/config/single/{key}` | Return a single config key. |
| `PUT` | `/config/single/{key}` | Update one config key with a JSON body like `{"value":{"value":"binance","type":"str"}}`. |
| `POST` | `/config/multiple` | Update multiple config keys in one JSON payload. |
| `POST` | `/config/live/activate` | Switch the instance from dry run to live mode after backend readiness checks pass. |
| `GET` | `/config/backup/export?include_trade_data=false` | Export config-only backup payload. |
| `GET` | `/config/backup/export?include_trade_data=true` | Export full backup payload including trade data. |
| `POST` | `/config/backup/restore` | Restore config-only or full backup payloads. |

Notes:
- Config update payloads use nested typed objects such as
  `{"dry_run":{"value":false,"type":"bool"}}`.
- Generic config saves cannot switch `dry_run` from `true` to `false`; that
  transition is rejected unless it goes through `POST /config/live/activate`.
- `POST /config/live/activate` expects `{"confirm": true}` and returns `409`
  with a `blockers` array when required setup is still incomplete.
- `POST /config/backup/restore` expects a JSON body with `backup` and optional
  `restore_trade_data`.
- Switching the signal plugin to `csv_signal` is rejected while open trades
  still exist.

## Orders

All mutating order endpoints use `POST`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/orders/sell/{symbol}` | Trigger a manual sell for a symbol. |
| `POST` | `/orders/buy/{symbol}/{ordersize}` | Trigger a manual buy / additional safety order. |
| `POST` | `/orders/stop/{symbol}` | Stop an active trade. |
| `POST` | `/orders/buy/manual` | Append a manual buy row without placing an exchange order. |

Manual buy payload:

```json
{
  "symbol": "BTC/USDT",
  "date": "2026-03-18T10:30:00Z",
  "price": 65000,
  "amount": 0.01
}
```

## Trades

### WebSocket streams

These streams are fan-out based: one producer loop refreshes shared data every
5 seconds and broadcasts it to all connected dashboard clients.

| Method | Path | Purpose |
| --- | --- | --- |
| `WS` | `/trades/open` | Stream open trades. |
| `WS` | `/trades/closed` | Stream the most recent closed trades page. |
| `WS` | `/trades/unsellable` | Stream unsellable archived remainders. |

### REST endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/trades/closed/length` | Return the total number of closed trades. |
| `GET` | `/trades/closed/{page}` | Return one closed-trades page. |
| `POST` | `/trades/closed/delete/{trade_id}` | Delete a closed trade. |
| `POST` | `/trades/unsellable/delete/{trade_id}` | Delete an unsellable trade after manual cleanup. |

## Statistics

| Method | Path | Purpose |
| --- | --- | --- |
| `WS` | `/statistic/profit` | Stream live profit / dashboard stats every 5 seconds. |
| `GET` | `/statistic/profit/{timestamp}/{period}` | Return profit stats for a given period. |
| `GET` | `/statistic/profit-overall/timeline` | Return the adaptive last-12-month profit timeline. |

The live profit stream includes current portfolio values plus runtime state such
as funds locked, funds available, Autopilot mode, effective max bots, and Green
Phase status.

## Market Data

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/data/ohlcv/{symbol}/{timerange}/{timestamp_start}/{offset}` | Return OHLCV data for charts. |
| `GET` | `/data/exchange/symbols/{currency}` | Return available exchange symbols for the configured exchange and quote currency. |
| `POST` | `/data/exchange/symbols` | Return exchange symbols using draft exchange settings from the request payload. |

Draft exchange-symbol lookup accepts a JSON body with optional `currency` and
`exchange_config` fields.

## Monitoring

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/monitoring/test` | Send a Telegram test notification using current or overridden monitoring settings. |

`POST /monitoring/test` accepts an optional JSON payload that overrides the
persisted monitoring config for the test request only.
