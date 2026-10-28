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
| `POST` | `/config/denylist/deny` | Append an open trade's base token to `pair_denylist` atomically, blocking future signal entries while existing open trades continue. |
| `GET` | `/config/backup/export?include_trade_data=false` | Export config-only backup payload. |
| `GET` | `/config/backup/export?include_trade_data=true` | Export full backup payload including trade data. |
| `POST` | `/config/backup/restore` | Restore config-only or full backup payloads. |

Configuration editors must read `config_revision` from `GET /config/all` and
send it as the decimal `X-Moonwalker-Config-Revision` header on either write
endpoint. Successful writes return the new `config_revision`. A missing, invalid
or stale revision returns HTTP 409; reload the form and reconcile changes before
retrying. Older API clients must be updated to send the header. Configuration
restores and operational configuration changes also invalidate older revisions.

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
- `POST /config/denylist/deny` expects a JSON body like
   `{"symbol": "FO0/USDT"}` and returns the resulting `pair_denylist` plus a
   `denied` marker. The append de-duplicates the base token and writes under a
  global config write lock so concurrent dashboard clients cannot clobber each
  other's denylists. Reversal is done by editing `pair_denylist`.
- `POST /config/backup/restore` expects a JSON body with `backup`,
  `confirm: true`, and optional `restore_trade_data`. Restore drains active
  exchange-order work, rejects new order work until replacement completes, and
  leaves the restored instance paused in dry-run mode. Backups containing
  removed legacy config keys are rejected.
- Full backups use schema 3 and include accumulation ownership, exact balances,
  historical execution records and pinned strategy dependencies. Restore retains
  closing/stopped states and quarantines unfinished orders and commands. Strategy
  catalog conflicts reject the restore. See [accumulation backup and restore](accumulation.md#backup-and-restore)
  for validation and recovery requirements. Legacy schema 1/2 backups remain
  readable. Full backups also carry the configured initial accumulation pin and
  its exact strategy dependency before any holding exists. Config-only restore
  does not replace trade or accumulation records and clears the initial pin so
  the operator must select a compatible local version.
- Switching the signal plugin to `csv_signal` is rejected while open trades
  still exist.

## Accumulation

Use the [operating guide](howto-operate-accumulation.md) for the dashboard flow and
the [accumulation reference](accumulation.md) for execution parameters and states.

These routes return `503` when the lifespan-owned accumulation runtime is not ready.
They do not construct a runtime or activate live trading. Configuration and Strategy
Builder include mode/pin selection and immutable-variant editing. `/config/all`
exposes read-only `accumulation_available` and a `trade_mode_switch_guard` snapshot.
Saving rechecks the guard; mode changes drain order work before taking the config
write lock and reject active exposure or unresolved placements. Live mode changes
also require an existing global pause. Accumulation requires enabled management,
spot, ASAP fixed symbols or CSV, and disabled Autopilot. The initial exact integer
`accumulation_strategy_version_id` is optional in an incomplete configuration draft
and required before demo or live accumulation execution. Dry run uses the exchange's
supported CCXT demo environment, demo credentials and demo wallet funds. It does not
fall back to live trading. Demo and live ownership scopes remain separate.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/accumulation/activations?limit=50&after=BTC%2FUSDC` | Read a symbol-ordered registry page; `limit` is 1–100 and `next_after` supplies the next cursor. |
| `GET` | `/accumulation/activation?symbol=BTC%2FUSDC` | Read one current activation, latest entry declaration summary and up to 20 recent lifecycle operations. |
| `POST` | `/accumulation/commands` | Journal revisioned lifecycle intent or archive verified closing dust; see action fields below. |
| `POST` | `/accumulation/entry/commands` | Correct, explicitly retry or abandon a staged entry. |
| `POST` | `/accumulation/repair` | Reconcile an existing order, retire unplaced intent, acknowledge recorded settlement, rebind or declare ownership, restore an inventory link, or record a paused correction. |
| `GET` | `/accumulation/performance` | Read exact coverage-aware returns and fresh bid valuation, grouped by quote. |
| `WS` | `/accumulation/performance/stream` | Stream shared valuation snapshots and the current activity revision. |
| `GET` | `/accumulation/activity` | Read a bounded page of cumulative order summaries and CSV declarations for the active account. |
| `POST` | `/accumulation/replay` | Compare a saved accumulation version with equal-funded buy-and-hold and fixed-interval DCA using supplied completed candles. No wallet or order actions. |
| `GET` | `/accumulation/strategies?limit=50&after_id=0` | Read a bounded catalog page of compatible immutable versions, template defaults and supported timeframes. |
| `POST` | `/accumulation/strategies` | Retired standalone dip writer; returns `410`. Create shared strategies through Strategy Builder. |

Registry pages and individual activation reads include a `portfolio` snapshot
covering all persisted accumulation holdings, independent of the page cursor.
`by_quote` keeps currencies separate and supplies exact `remaining_cost`, a
`known_remaining_cost` subtotal and `unknown_cost_count`. Unknown totals are null;
`unverified_holding_count` identifies missing ownership links. These are cost
figures; `valuation_available` remains false.

Individual reads also include `orders` (up to 20 cumulative filled-order
checkpoints) and `older_orders_available`. Each row exposes exact filled quantity,
gross quote amount, reported per-currency fees, completion flags, last evidence
update time and `inventory_at_update`. It does not expose raw exchange payloads
or account scope. Order history survives full close and can span previous holdings
of the symbol. Corrections replace a checkpoint instead of duplicating an order.

`quarantined_orders` lists up to 20 recorded placement operation IDs, sides and
whether a durable exchange lookup identity exists. To reconcile one, POST exactly
`symbol`, `action: "repair_order"`, a stable `operation_id`, `expected_revision`
and `placement_operation_id` to `/accumulation/repair`. The account comes from
server configuration. An explicitly paused activation and matching ownership are
required. The response uses the normal `operation` envelope: `202` with status
`quarantined` means terminal evidence is still needed; explicitly retry the same
body for a fresh lookup. `200` with status `applied` means complete terminal
evidence was atomically reconciled. No repair request places or cancels an order
or enables buying. A repaired close with a remainder has status `reconciled` and
requires an explicit `retry_close` command before any further sale.

Activation reads also include `quarantined_commands` (up to 20 unplaced
interrupted commands) and `close_predecessor` independently of recent request
history. To retire one command, POST exactly `symbol`, `action: "retire_command"`,
a stable `operation_id`, `expected_revision` and the reviewed command's
`previous_operation_id` to `/accumulation/repair`. This transaction requires an
explicit pause, matching account/holding ownership and no pending command,
unresolved placement or opportunity commitment. It cancels the old intent and
journals an applied receipt; it does not call the exchange. Existing quantities,
cost, pins and consumption guards are preserved. A close remains CLOSING and needs
a new `retry_close` referencing the retired predecessor; an unadopted entry keeps
its declaration for a new explicit staged-entry decision. Reused request IDs must
carry the identical body. The normal `200` applied / `400` invalid / `409` conflict
responses apply.

Status reads include `account_matches` (`true`, `false`, or `null` when current
credentials cannot be compared). They never return the opaque account scope or
credentials. To revalidate a rotated key, POST exactly `symbol`,
`action: "rebind_account"`, a stable `operation_id` and `expected_revision` to
`/accumulation/repair`. The destination is always the server-configured account;
the client cannot supply an account label or scope.

This supports intact, settled native ownership with complete fees and stored
client/exchange identities for the first and latest filled-order anchors. Signed
lookups must match the original order totals and identities; fresh free inventory
must cover the managed quantity, with no open symbol orders or shared managed
base-asset ownership. A similar wallet balance is not sufficient proof. An eligible
request is journaled and pauses the holding before reads. Atomic completion changes
only the binding and keeps buying paused; close/stopped latches and exact ledger
values remain unchanged. `202`/`quarantined` requires an explicit same-body retry
for missing evidence; `200`/`applied` records the completed binding. Stale, different
or unsupported account evidence fails without adopting the scope. Imported
inventory, absent anchors and unresolved original-account work need separate repair.

Paused inventory corrections use `/accumulation/repair` with exactly:

```json
{
  "symbol": "BTC/USDC",
  "action": "adjust_inventory",
  "operation_id": "operator-generated-stable-id",
  "expected_revision": 12,
  "direction": "add",
  "quantity": "0.000000000000000001",
  "acquisition_cost": "0.000000000000000009",
  "note": "Correct imported net quantity"
}
```

`direction` is `add` or `remove`. Quantity must be a positive decimal string;
`acquisition_cost` is a nonnegative decimal string or `null` for an addition,
and must be `null` for a removal. Removals allocate proportional existing cost
and must retain positive inventory. Unknown added cost propagates to remaining
cost and contributed quote; unknown existing totals stay unknown. A reason of
1–500 characters without control characters is required. No client-supplied
account scope, target quantity, fee total or before/after snapshot is accepted.

The service requires intact ownership in the current account, initialized and
explicitly paused state, settled orders and fee evidence, no unresolved commands,
and fresh free-wallet coverage for the resulting quantity. It rechecks state
after signed reads and atomically writes the inventory plus an applied receipt.
The same ID/body retrieves that receipt without another change; a conflicting
reuse returns `409`. The result stays paused and no order or checkpoint is
created. Existing fees, proceeds, strategy and purchase guards are preserved.
Quantity and cost corrections receive `operator_adjusted` provenance and
incomplete execution history. The operation projection includes a sanitized
`adjustment` receipt (direction, quantity, note, before/after quantity and cost);
the full audit remains persisted and included in backups. CLOSING, STOPPED,
account changes and broken ownership links require their separate workflows.

Statistics payloads now expose `performance_complete` and `performance_scope`.
While accumulation registrations or holdings exist, the legacy numeric profit
fields cover Dynamic DCA only (`dynamic_dca_only`); they must not be presented as
complete portfolio returns. The dashboard withholds those totals and new overall
chart samples when native return coverage is incomplete. With verified native
coverage in the configured quote, those totals include accumulation.

`GET /accumulation/performance` provides exact decimal market value, realized,
unrealized and total return grouped by quote currency. `null` means unknown,
never zero. The report includes coverage, observation time, a mark-validity
deadline, and verified UTC dated realized totals. Fresh bids are used before
future sale fees. Changing ledgers, stale marks, foreign account scopes and
unverified history prevent complete coverage. This endpoint is unavailable in
recovery-only sessions because those permit database-only status reads and
explicit reconciliation. Dashboard totals combine verified native returns only
when every group uses the configured quote; no FX conversion is guessed.

The same snapshot includes `holdings`, with symbol, net quantity, remaining
cost, average remaining cost per coin, bid value, unrealized return, completeness
and basis provenance. Amounts are decimal strings; unavailable amounts are
`null`. Average cost is calculated with 512-digit decimal precision and is
unavailable when quantity is zero or the basis is unknown. Values and returns
use the same evidence and bid snapshot as the
quote-currency totals.

`GET /accumulation/activity` returns up to 20 records and a `next_cursor`.
Order records summarize the latest cumulative checkpoint for an exchange order;
CSV records describe declarations, not exchange fills. Results are scoped to
the active account and ordered by update time. Pass the cursor unchanged to get
the next page. The snapshot expires after five minutes or a server restart; any
activity correction, insertion or deletion also invalidates it. A stale cursor
returns HTTP 409 and the client must restart the history. UTC timestamps are
returned and can be displayed in the client's timezone.
Each activity record's `price_per_coin` divides its recorded quote amount by
its quantity. For exchange orders, this is the cumulative execution price before
fees; for CSV declarations it is declared basis per net coin. It is `null` when
the required amounts are unknown or not positive.
The performance stream sends `snapshot` messages containing `performance` and
`activity_revision`; an `unavailable` message indicates a temporary failure.
Dashboard clients retain the last snapshot during reconnects and stop showing
bid-based values after its validity deadline. A changed activity revision
causes the activity list to reload automatically.

Read responses include zero-inventory registrations and STOPPED records. Quantity,
cost, contributions, proceeds and fee amounts remain exact decimal strings;
unknown values remain `null`. Fee totals with pending reports are incomplete, and
`fees: null` means missing or invalid evidence. A missing holding is not a synthetic
zero balance. `holding_integrity: invalid` hides inconsistent ownership instead
of projecting another holding's inventory. Each page/detail reads one database
snapshot; separate pages can observe intervening changes. No exchange reads or
mutations occur. `runtime_wait_reason` is advisory process-local status; persisted
state and revision remain authoritative. Account scopes, raw requests, strategy
documents and exchange payloads are not returned.

Both command endpoints require `symbol`, `action`, a stable `operation_id` and
`expected_revision` from the current activation snapshot. Unknown fields are
rejected; account identity comes from the server. Lifecycle actions are `pause`,
`resume`, `close`, `retry_close`, `archive_dust`, `sell_partial`, `switch_strategy`
and `reactivate`. `operation_id` must match `^[A-Za-z0-9._:-]{1,64}$`;
`expected_revision` is an integer from 0 through `2**63 - 2` (booleans rejected).

| Lifecycle action | Additional required fields |
| --- | --- |
| `pause`, `resume`, `close`, `reactivate` | None. |
| `retry_close`, `archive_dust` | `previous_operation_id`: valid operation ID of the reviewed close predecessor. |
| `sell_partial` | `quantity`: finite positive decimal string, at most 128 characters, leaving positive inventory. |
| `switch_strategy` | `target_version_id`: integer in `1..2**63 - 1`, identifying an exact compatible version. |

Sales remain explicit operator actions and execute only in the runtime worker.
`archive_dust` uses the same command endpoint but places no order. It atomically
moves only a verified unsellable full-close remainder into Unsellable trades and
stops the registration. Sellable inventory, stale or changed ownership, unsettled
execution and incomplete fees block archival. Full-close workers also invoke this
archival automatically after verifying the same evidence. Partial sales do not.
See [the recovery guide](howto-recover-accumulation.md#finish-a-full-close).

Entry actions are `retry_entry`, `correct_import` and `abandon_entry`. Each also
requires `previous_operation_id` from the latest entry operation. Correction
requires `csv_content` for that symbol and remains staged; `retry_entry` performs
fresh ownership validation. Abandonment does not sell or discard owned inventory.
It retains a STOPPED registry for an entry whose inventory was never adopted.

Responses contain `operation` with its persisted `status`, `state`, `revision` and
`reason`. `202` means pending work, including a correction waiting for explicit
retry or a failed validation still requiring attention; it does not promise
automatic completion. `200` returns a nonpending journal outcome. Repeated IDs
return their historical outcome, which may differ from current activation state;
refresh the status endpoint before a new action. Changed reuse of an ID or stale
revision returns `409`; invalid input returns `400`; missing status records return
`404`. Existing trusted-host and browser-origin protections apply to these routes.

The strategy catalog scans at most `limit` stored versions (1–100) per page and
omits incompatible documents. An empty `versions` list can still have a
`next_after_id`; follow that cursor to continue past ordinary DCA versions. Every
returned entry includes its exact database `id`, name, version, validated
parameters and required history. Use that ID as `target_version_id` in an explicit
`switch_strategy` command. The runtime validates compatibility before journaling,
then settles outstanding orders and validates fresh market/account evidence before
rebinding. Switching preserves purchase consumption and a prior pause.

The standalone `POST /accumulation/strategies` writer is retired. It returns
`410` with `code: "retired_strategy_writer"` while the runtime is available and
does not create or change any records. Use the shared Strategy Builder instead.
Legacy standalone dip presets are excluded from both selector catalogs; existing
version IDs remain readable for historical pins, replay and recovery. Their
immutable documents are not rewritten or removed from referenced history.
See the [shared strategy reference](strategies.md#shared-strategies-for-dca-and-accumulation).

## Autopilot Memory

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/autopilot/memory` | Return the persisted Autopilot Memory read model used by `/control-center/autopilot`. |

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
| `POST` | `/orders/stop/{symbol}` | Close a DCA trade's ledger at its latest tracked market price, without selling coins. |
| `POST` | `/orders/buy/manual` | Append a manual buy row without placing an exchange order. |

The sell, buy, and stop endpoints retain their legacy `result` field and also
return a typed `mutation` object. Its `status` is one of `applied`,
`deduplicated`, `rejected`, `stale`, `indeterminate`, or `quarantined`.

Stop records a closed trade with reason `manual_stop` and preserves actual
execution history, including earlier partial-sale proceeds. Realized P&L is
unavailable because the existing partial-sale ledger does not establish complete
fee evidence. The
remaining coins' quantity and latest tracked price are stored separately as
`valuation_quantity` and `valuation_price`; they are not sell executions or
realized P&L. No sell order or hypothetical sell fee is created. Coins remain on the exchange
for the operator to manage. Pending take-profit orders must be safely canceled
or reconciled first. Missing or invalid prices reject the stop and retain the
open trade. Previously stopped trades whose history was deleted are not rebuilt.
Legacy manual-stop summaries without a separate valuation are withheld from
realized profit. When such records are present during migration or restore,
existing profit snapshots are marked unverified and the overall timeline returns
HTTP 409 when unverified snapshots fall in its one-year window; snapshot values
are retained for reconciliation. If an old stop was deleted before backup or
migration, its effect on old snapshots cannot be identified from the remaining
records. A partial-sale stop
with unverified fees also makes period profit history unavailable (HTTP 409) and
disables profit-based capital stretch.

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

Accumulation snapshots are shared across dashboard clients with matching symbol,
account scope and runtime state. Each connection receives an initial snapshot;
subsequent builds follow runtime/lifecycle change events. Slow subscribers keep
only the newest notification. The projection cache is bounded and cleared on
state changes, last-client disconnect and shutdown. Clients never start the
trading worker, and snapshot sharing does not introduce status polling.


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
| `GET` | `/trades/executions/{deal_id}` | Return chronological execution rows for one deal replay. |
| `GET` | `/trades/replay/indicators/{deal_id}/{timerange}/{start}/{end}` | Return strategy indicator overlays for one bounded trade replay window. |
| `POST` | `/trades/closed/delete/{trade_id}` | Delete a closed trade. |
| `POST` | `/trades/unsellable/delete/{trade_id}` | Delete an unsellable trade after manual cleanup. |
| `POST` | `/trades/unsellable/delete/all` | Delete all unsellable trades after manual cleanup. |
| `POST` | `/trades/mission/pause/{symbol}` | Pause automation for one open mission. |
| `POST` | `/trades/mission/resume/{symbol}` | Resume automation for one open mission. |

The executions response retains its native `result` array and additionally returns
`declared_purchases` and `declaration_status` (`none`, `available`, or `unavailable`).
Accumulation CSV purchases include exact decimal strings for price, net amount,
fee-inclusive order size, per-currency fees, whether fees are known, and
`provenance: "csv_declaration"`. These are declarations of prior purchases, not
exchange executions. Only validated adopted receipts bound to this exact deal
are returned. Ambiguous or corrupt receipts yield no declared rows and an
unavailable status; they never borrow purchases from an earlier holding cycle.
The dashboard loads this history when expanding the existing trade card, rather
than broadcasting CSV rows in routine status updates.

The replay indicator response uses the strategies recorded in the deal's
execution history. For an open deal, it also includes the currently configured
`dca_strategy`, even before a safety order executes. The `source` field is
`execution_ledger_and_active_dca` when both contribute. Closed deals use their
recorded strategy history; later DCA configuration changes do not alter their
indicator overlays. A plotted indicator shows the strategy's calculated values,
not that a safety-order signal or fill occurred at that candle.

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

The optional `mode=dynamic_dca` or `mode=unknown` filter scopes the closed-trade
analytics to the last two years. `unattributed_trades` counts closed records in
that period whose lifecycle mode is unknown. AI Trust remains independently
scoped across modes. Omitting `mode` retains the unfiltered response. Older
closed records are attributed to accumulation only when matching deal,
activation and order evidence is available; other records remain unclassified.

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

Additional accumulation repair actions use the common `symbol`, `action`,
`operation_id` and `expected_revision` fields:

| Action | Additional fields | Result |
| --- | --- | --- |
| `declare_ownership` | `confirmation`: exact full symbol; `note`: 1–500 characters | Explicit declaration under changed credentials, fresh wallet coverage, unchanged money and buying paused; history becomes unverified. |
| `restore_inventory` | None | Rebuild/relink only exact server-held inventory evidence after fresh wallet validation; no client quantity/cost accepted. |
| `acknowledge_settlement` | `previous_operation_id`: quarantined sale command | Acknowledge already-recorded completed placement and complete latest checkpoint; no exchange action. Remaining close quantity stays Closing. |

Staged `retry_entry` and `correct_import` may also specify a compatible integer
`target_version_id`. They apply only before adoption, retain the reviewed
predecessor identity and never silently replace the strategy of an owned holding.
An abandoned never-adopted registration can be explicitly validated again.
The activation projection includes `inventory_restore_required` to distinguish
missing recorded coins from legitimate empty registrations.

`POST /accumulation/replay` requires `strategy_version_id`, positive decimal-string
`funding`, decimal-string `fee_bps` and `slippage_bps` (0–1000), integer
`fixed_interval_candles` (1–20000), and `candles`: a list of objects containing
`close_ms`, `open`, `high`, `low`, `close`. Prices are exact positive decimal strings;
closing timestamps are aligned UTC integer milliseconds. Supply bounded warmup plus
at least two evaluation candles, at most 20000 candles. It returns equal-funding
results, fee/cash/unit totals, sampled drawdown, gaps, signal counts, at most the
first 100 accumulation executions, and modeling/survivorship caveats. This endpoint
uses no account credentials and cannot trade. Normal runtime availability is
required; recovery-only sessions reject it.

### Accumulation status stream

`WS /accumulation/stream?symbol=BTC%2FUSDC` is a read-only, origin-checked stream.
It sends `{ "type": "snapshot", "page": ..., "detail": ... }` on connection,
then when runtime wait state, observations or lifecycle revisions change. Slow
subscribers retain one pending notification. The page uses the first 25 symbols;
`detail` always refers to the requested symbol (or the first symbol when omitted).
A reconnect receives current state rather than replaying commands. An unavailable
runtime sends `{ "type": "unavailable" }` and ends the stream. Repair-only startup
keeps its existing WebSocket gate; REST pages advertise `stream_available: false`.

Status projections optionally include `wait_condition`: a reason, timeframe,
`observed_close_ms`, `observed_price`, `next_close_ms`, and `levels`. Each level
provides `kind`, `direction`, exact decimal `target_price` and signed
`change_percent`. Multiple rearm levels are alternatives; a
`recovery_then_correction` level requires a later correction. Percentages use the
last completed close, or the fresh ask when `price_basis` is `ask`. Evidence must
match the activation, current revision, pinned strategy, wait reason and candle
validity window; otherwise `wait_condition` is null. These fields never authorize
an order or change the trading strategy.

For `WAIT_CONDITIONS`, graph strategies can include `strategy_conditions`: the
evaluated condition tree with all/any groups, comparison operands and outcomes
from that completed candle. A null comparison outcome means an operand was
unavailable. Large trees may be truncated; the root outcome remains authoritative.
The next candle recalculates these values, and passing the graph alone does not
guarantee a buy.


## Backtest

`POST /backtest/run` is the shared simulation endpoint. Dynamic DCA accepts its
existing `strategy_slug`, timeframe and DCA sizing/exit fields. Accumulation uses
`trade_mode: "accumulation"`, `symbol`, exact `strategy_version_id`, `start_date`
and `end_date`; its timeframe must match the exchange configuration. Optional modeling
inputs are `funding` (positive quote amount, default `"1000"`), `fee` (fraction,
default `0.001`), `slippage_bps` (0–1000, default `"20"`) and
`fixed_interval_candles` (integer 1–20000, default `24`). No live configuration,
wallet inventory or strategy assignment is changed.

Accumulation fetches spot history including the saved strategy's warmup and
excludes incomplete candles. The 20000-bar limit includes warmup. The response
uses the usual `stats` and `chart` envelope, with buy markers; `trades` is empty
because no closed Dynamic DCA deals are fabricated. The `accumulation` report
contains exact modeled buy executions and equal-funding comparison results,
including unsold coins and cash. Execution rows and chart markers are capped at
100 buys with `trades_truncated` disclosure; totals include every modeled buy.
A bad input or insufficient warmup returns 400; an occupied replay worker returns
409. The supplied-candle `/accumulation/replay` API remains supported.
