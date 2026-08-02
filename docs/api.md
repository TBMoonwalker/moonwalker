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
| `GET` | `/assets/{file_path}` | Serve hashed Vite frontend bundles from the built assets directory. |
| `GET` | `/static/{file_path}` | Serve built frontend assets. |

## Configuration

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/config/all` | Return the dashboard config snapshot with persisted credentials replaced by redaction markers, including snapshot-native `config_updated_at` metadata for stale-snapshot detection. |
| `GET` | `/config/freshness` | Return the latest persisted config `updated_at` timestamp so dashboard clients can detect stale local snapshots. |
| `GET` | `/config/schema` | Return the versioned, frontend-safe contract for high-risk runtime settings, including defaults, bounds, enums, sensitivity, and readiness metadata. |
| `GET` | `/config/single/{key}` | Return a single config key. |
| `PUT` | `/config/single/{key}` | Update one config key with a JSON body like `{"value":{"value":"binance","type":"str"}}`. |
| `POST` | `/config/multiple` | Update multiple config keys in one JSON payload. |
| `POST` | `/config/live/activate` | Switch the instance from dry run to live mode after backend readiness checks pass. |
| `POST` | `/config/trading/pause` | Pause new exposure while existing exit management continues. |
| `POST` | `/config/trading/resume` | Resume admission of new exposure. |
| `GET` | `/config/backup/export?include_trade_data=false` | Export config-only backup payload. |
| `GET` | `/config/backup/export?include_trade_data=true` | Export full backup payload including trade data. |
| `POST` | `/config/backup/restore` | Restore config-only or full backup payloads. |

Notes:
- Every HTTP and WebSocket request must use a trusted private/loopback Host or an
  explicitly allowed Host. Unsafe browser requests (`POST`, `PUT`, `PATCH`, and
  `DELETE`) additionally require an allowed same-origin value and the
  `X-Moonwalker-Client: dashboard` header. Direct trusted-LAN clients without an
  `Origin` header remain supported. Set `MOONWALKER_ALLOWED_HOSTS` for explicit
  local DNS names and `MOONWALKER_ALLOWED_ORIGINS` for trusted reverse proxies.
- Config update payloads use nested typed objects such as
  `{"dry_run":{"value":false,"type":"bool"}}`.
- Public config reads never return persisted credential values. They use
  redaction markers that supported config writes restore from server state when
  an unrelated setting is saved.
- Dashboard clients can compare `/config/all`'s `config_updated_at` against
  `/config/freshness` so a stale snapshot is not mistaken for a freshly loaded
  one when another tab or client saves between requests.
- Config update endpoints reject removed legacy keys such as
  `autopilot_max_fund`, `autopilot_entry_stretch_max_multiplier`,
  `trade_lifecycle_mode`, `dynamic_dca`, and `sidestep_campaign_enabled`; use
  `capital_max_fund`, `autopilot_base_order_stretch_max_multiplier`, and
  canonical `trade_mode` instead.
- Generic config saves cannot switch `dry_run` from `true` to `false`; that
  transition is rejected unless it goes through `POST /config/live/activate`.
- `POST /config/live/activate` expects `{"confirm": true}` and returns `409`
  with a `blockers` array when required setup is still incomplete.
- `POST /config/trading/pause` and `POST /config/trading/resume` both expect
  `{"confirm": true}`. Pausing blocks new exposure but does not block protective
  exits for existing positions.
- `POST /config/backup/restore` expects a JSON body with `backup`,
  `confirm: true`, and optional `restore_trade_data`. Restore drains active
  exchange-order work, rejects new order work until replacement completes, and
  leaves the restored instance paused in dry-run mode. Backups containing
  removed legacy config keys are rejected.
- Switching the signal plugin to `csv_signal` is rejected while open trades
  still exist.

## Autopilot Memory

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/autopilot/memory` | Return the persisted Autopilot Memory cockpit read model used by `/control-center/autopilot` and the Control Center overview preview. |

The Autopilot Memory payload is read-only. It includes:
- current memory status (`fresh`, `warming_up`, `stale`, or baseline-only)
- favored and cooling trust-board rows with confidence, reasons, adaptive TP
  delta, and suggested base order
- one featured symbol summary for the overview cards
- recent smart-play events in operator-facing language
- portfolio-effect ranges for adaptive TP and suggested base order
- entry-sizing status, warmup progress, and stale markers

## Strategy Builder

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/strategies` | Return strategy summaries and the available node palette. |
| `GET` | `/strategies/{slug}` | Return one strategy, its active graph IR, validation result, explanation, and palette. |
| `POST` | `/strategies` | Create a blank custom strategy with `{"name":"My strategy"}`. |
| `POST` | `/strategies/duplicate` | Duplicate a built-in or custom strategy with `{"source_slug":"ema20_swing","name":"My copy"}`. |
| `POST` | `/strategies/validate` | Validate a draft graph with `{"ir":{...}}` without saving it. |
| `PUT` | `/strategies/{slug}` | Validate and promote a custom graph as a new active version with `ir` and `base_lock_version`. |
| `DELETE` | `/strategies/{slug}` | Delete a custom strategy. Built-in strategies cannot be deleted. |

Active graph versions are immutable. A save uses `base_lock_version` for
optimistic concurrency and returns `409` when another dashboard client saved a
newer version first. Built-in strategies are read-only templates; duplicate one
before editing it.

## Orders

All mutating order endpoints use `POST`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/orders/sell/{symbol}` | Trigger a manual sell for a symbol. |
| `POST` | `/orders/buy/{symbol}/{ordersize}` | Trigger a manual buy / additional safety order. |
| `POST` | `/orders/stop/{symbol}` | Stop an active trade. |
| `POST` | `/orders/buy/manual` | Append a manual buy row without placing an exchange order. |

The sell, buy, and stop endpoints retain their legacy `result` field and also
return a typed `mutation` object. Its `status` is one of `applied`,
`deduplicated`, `rejected`, `stale`, `indeterminate`, or `quarantined`.
For confirmed buy and sell requests, clients should send an
`X-Moonwalker-Operation-Id` header containing 1-64 letters, numbers, or the
characters `._:-`. Reuse the exact same value only when retrying the same
confirmed action; using a new value creates a new exchange-placement identity.
Moonwalker generates a fallback identity when the header is omitted.

The response `operation_id` is the durable identity used to deduplicate and
reconcile the exchange effect. An `indeterminate` or `quarantined` response is
not success and must not trigger another placement. Surface the operation ID
for manual reconciliation.

```http
POST /orders/sell/btc-usdt HTTP/1.1
X-Moonwalker-Operation-Id: manual-sell-btc-20260802-01
```

```json
{
  "result": "",
  "mutation": {
    "operation_id": "manual-sell-btc-20260802-01",
    "symbol": "BTC/USDT",
    "action": "manual_sell",
    "status": "indeterminate",
    "reason_code": "exchange_outcome_indeterminate",
    "user_message": "The exchange may have accepted this order.",
    "exchange_order_id": null,
    "client_order_id": "mw-...",
    "persisted_execution_id": null
  }
}
```

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
| `WS` | `/trades/waiting` | Stream waiting sidestep campaign summaries. |

### REST endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/trades/closed/length` | Return the total number of closed trades. |
| `GET` | `/trades/closed/{page}` | Return one closed-trades page. |
| `GET` | `/trades/executions/{deal_id}` | Return chronological execution rows for one deal replay; Waiting clients may add `campaign_id` to span the persisted sidestep campaign. |
| `GET` | `/trades/replay/indicators/{deal_id}/{timerange}/{start}/{end}` | Return strategy indicator overlays for one bounded trade replay window; Waiting clients may add `campaign_id` to resolve prior campaign strategy snapshots. |
| `POST` | `/trades/closed/delete/{trade_id}` | Delete a closed trade. |
| `POST` | `/trades/unsellable/delete/{trade_id}` | Delete an unsellable trade after manual cleanup. |
| `POST` | `/trades/unsellable/delete/all` | Delete all unsellable trades after manual cleanup. |
| `POST` | `/trades/waiting/stop/{campaign_id}` | Stop a waiting sidestep campaign. |
| `POST` | `/trades/waiting/activate/{campaign_id}` | Force a waiting sidestep campaign back into an active long leg. |
| `POST` | `/trades/mission/pause/{symbol}` | Pause automation for one open or waiting mission. |
| `POST` | `/trades/mission/resume/{symbol}` | Resume automation for one open or waiting mission. |

The optional `campaign_id` query parameter on the execution and indicator
replay endpoints is a read-only Waiting-chart context. Both identifiers must be
UUIDs. Moonwalker uses the persisted campaign execution ledger only when the
campaign is a sidestep replay timeline; Open and Closed clients continue using
the deal-only form.

## Statistics

| Method | Path | Purpose |
| --- | --- | --- |
| `WS` | `/statistic/profit` | Stream live profit / dashboard stats every 5 seconds. |
| `GET` | `/statistic/profit/{timestamp}/{period}` | Return profit stats for a given period. |
| `GET` | `/statistic/profit-overall/timeline` | Return the adaptive last-12-month profit timeline. |

The live profit stream includes current portfolio values plus runtime state such
as funds locked, exchange-free funds, funds actually tradable after global
capital-budget headroom, Autopilot mode, effective max bots, and Green Phase
status.

Capital-budget fields include `capital_max_fund`,
`capital_effective_max_fund`, `capital_stretch_quote`,
`capital_funds_locked`, `capital_open_trade_reserve`,
`capital_pending_quote`, `capital_available_quote`,
`capital_budget_available`, and `capital_budget_reason`.

It also carries compact Autopilot Memory status fields for the top statistics
strip, including freshness or warmup state, stale reason, current vs required
closed-trade count, and the currently featured symbol when available.

## Analytics

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/analytics/overview` | Return closed-trade analytics plus AI Trust coverage, warning quality, recent predictions, outcome review, and read-only local calibration diagnostics. |

## Market Data

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/data/ohlcv/{symbol}/{timerange}/{timestamp_start}/{offset}` | Return OHLCV data for charts. |
| `GET` | `/data/ohlcv/{symbol}/{timerange}/{timestamp_start}/{timestamp_end}/{offset}` | Return bounded OHLCV data for replay windows. |
| `GET` | `/data/ohlcv/replay/{deal_id}/{timerange}/{offset}` | Return archived replay OHLCV data for a closed deal. |
| `GET` | `/data/ohlcv/replay/{deal_id}/{timerange}/{timestamp_start}/{timestamp_end}/{offset}` | Return archived replay OHLCV data for a closed deal within a bounded window. |
| `GET` | `/data/exchange/symbols/{currency}` | Return available exchange symbols for the configured exchange and quote currency. |
| `POST` | `/data/exchange/symbols` | Return exchange symbols using draft exchange settings from the request payload. |

Draft exchange-symbol lookup accepts a JSON body with optional `currency` and
`exchange_config` fields.

Replay OHLCV endpoints are used by the shared trade replay chart. Closed Trades
prefers archived replay candles when a deal archive exists and falls back to
bounded shared ticker history only for older legacy rows.

## Monitoring

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/monitoring/logs` | Return the allowlisted log sources visible in the Monitoring page. |
| `GET` | `/monitoring/logs/{source}` | Return tailed or backfilled log lines for one allowlisted source. |
| `GET` | `/monitoring/logs/{source}/download` | Download the current file for one allowlisted log source. |
| `POST` | `/monitoring/test` | Send a Telegram test notification using current or overridden monitoring settings. |

`GET /monitoring/logs/{source}` accepts:
- `limit` for batch size
- `cursor` to request newer complete lines after the current tail
- `before` to request older lines before the current oldest batch

`POST /monitoring/test` accepts an optional JSON payload that overrides the
persisted monitoring config for the test request only.
