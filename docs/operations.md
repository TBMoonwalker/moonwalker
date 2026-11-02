# Operations

## CI / Tests
Run the full backend and frontend verification suite:
```bash
cd scripts && ./ci.sh
```

Current CI checks include:
- backend format (`ruff format --check`)
- backend lint (`ruff`)
- backend import ordering (`isort --check-only`)
- backend type checking (`mypy`)
- backend guardrail checks
- backend pytest suite with line and branch coverage
- global and critical-module backend coverage ratchets
- frontend type-check (`vue-tsc`)
- frontend legacy/rendered checks (`node --test`)
- frontend unit and component tests (`Vitest`)
- frontend coverage ratchets
- frontend production build (`vite build`)
- dry-run Playwright journeys on desktop, mobile, and tablet in GitHub CI
- Python and npm vulnerability audits plus npm registry signature checks

## Runtime Model

Moonwalker runs as a single-node, single-instance application.

- one instance owns its own DB, config, watcher state, and trading engine
- multiple dashboard clients can connect to the same instance concurrently
- websocket streams are shared fan-out producers, not one producer per client

`./run.sh start` builds the frontend, copies the assets into the backend,
creates or reuses `.venv`, installs backend requirements, and starts the
Litestar app in the background.

Production supervisors should invoke `./run.sh start` or perform the same
requirements installation step before launching `backend/app.py` directly.
Starting `backend/app.py` from an existing virtual environment bypasses
dependency synchronization after an upgrade.

## Minimum supported version

Moonwalker declares a minimum supported version (MSV). Legacy migration and
compatibility code that predates it is kept only until an install is known to
have reached the floor.

- **Minimum supported version:** `4.9.0.0`, the sidestep-removal release.
- **Posture:** report only. A `preflight_msv` step runs at startup, before any
  schema or config migration callback, and records the install's baseline. It
  **never blocks startup** and **never mutates a ledger**: an install that
  predates the floor still loads and runs.

The preflight reports three outcomes:

- `supported` — the install's configuration ledger already contains the
  `2026-09-sidestep-removal-v1` migration row, so it has run at or after the
  floor.
- `unsupported` — the install has schema history (it is not fresh) but its
  configuration ledger predates the floor. Startup logs a `WARNING` with the
  upgrade path and the dashboard reports the same state at
  `GET /monitoring/msv`.
- `fresh` — no ledger history at all. Treated as supported; it will receive the
  current migrations on the same startup.

### Why the configuration ledger is the floor signal

The floor release deliberately added no schema migration, so a `4.8.x` and a
`4.9.x` database share an identical schema ledger and cannot be told apart
structurally. The non-self-healing marker that an install reached the floor is
the `2026-09-sidestep-removal-v1` row in the `config_migrations` ledger.
Databases that ran the floor release carry the row from that release onward.
Databases created after the trade-mode migration was removed receive the row
on their first startup only if they carry no pre-floor legacy bridge keys; a
database that still carries those keys is left unmarked and keeps reporting
`unsupported`, so the row stays a true floor signal rather than a self-healing
one.

### Upgrade path for a pre-floor install

1. Upgrade the installation through `4.9.0.0`.
2. Save the configuration and export a fresh full backup through the backup tool,
   so any removed legacy bridge is gone from the persisted data.

The trade-mode bridge removal shipped first under that gate; the remaining
removal passes stay gated on every install reaching `4.9.0.0`.

> **Changelog drift reconciled (B2 removal pass, 2026-11-01).** The
> `4.0.0.0` changelog entry claimed the legacy trade-mode config keys
> (`trade_lifecycle_mode`, `dynamic_dca`, `sidestep_campaign_enabled`) are no
> longer migrated; that claim was never true — the trade-mode bridge did not
> exist in that release, and once `2026-09-sidestep-removal-v1` arrived with
> `4.9.0.0` it canonicalized the keys until this removal. That migration and
> its guards are now gone, the historical entry is corrected, and the
> unreleased changelog entry documents the current restore behavior.

## Shared local Redis

Separate Moonwalker installations can reuse the Redis server on
`localhost:6379`. Startup reuses an available server or launches one in a
separate process session. Stopping or restarting Moonwalker closes only that
instance's Redis connections and leaves the shared server running, including
when that instance originally launched it.

Manage Redis separately with your operating system's service manager. On macOS,
`brew services start redis` keeps it managed independently of Moonwalker.
Redis may therefore remain running after all Moonwalker instances have stopped;
stop it separately only when no application needs it.

## Dashboard origin policy

Moonwalker allows same-origin dashboard HTTP and WebSocket connections by
default. This is the normal setup when the UI is served by Moonwalker itself.
Every HTTP and WebSocket request validates the Host authority as private,
loopback, or explicitly allowed so DNS rebinding cannot turn an attacker-owned
hostname into a trusted dashboard.

If a dashboard is hosted at another origin, set a comma-separated explicit
allowlist before starting Moonwalker:

```bash
MOONWALKER_ALLOWED_ORIGINS=https://dashboard.example.com ./run.sh start
```

For a LAN dashboard on another port:

```bash
MOONWALKER_ALLOWED_ORIGINS=http://192.168.6.5:3000 ./run.sh start
```

Reverse proxies should serve the dashboard and Moonwalker API from the same
public origin when possible. Otherwise, add the proxy's public origin to the
allowlist. Entries must be complete `http://` or `https://` origins without a
path, query, credentials, or wildcard. Invalid entries stop startup rather than
silently opening cross-origin access.

When Moonwalker is reached through a stable local DNS name or reverse-proxy Host,
allow that authority explicitly:

```bash
MOONWALKER_ALLOWED_HOSTS=moonwalker.local,proxy.example.com ./run.sh start
```

## Logging
You can see information about DCA and TP status in `statistics.log`. Other logs
are available as well (for exchange, controller, monitoring, etc.).

### Debug
Start Moonwalker with:
```bash
./run.sh start -d
```

### Trace
Start Moonwalker with:
```bash
./run.sh start -t
```
or:
```bash
./run.sh start --trace
```

### Log Level Environment Variable
You can override log level directly with `MOONWALKER_LOG_LEVEL`:
- `TRACE`
- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`
- `CRITICAL`

Examples:
```bash
MOONWALKER_LOG_LEVEL=INFO ./run.sh start
MOONWALKER_LOG_LEVEL=TRACE ./run.sh start
```

Priority order:
1. `MOONWALKER_LOG_LEVEL` (if set)
2. `MOONWALKER_DEBUG=True` (set by `./run.sh start --debug`)
3. Default `INFO`

## Dashboard Streams

Main live dashboard endpoints:
- `WS /trades/open`
- `WS /trades/closed`
- `WS /trades/unsellable`
- `WS /statistic/profit`

Main REST statistics endpoint:
- `GET /statistic/profit-overall/timeline`

These WebSocket streams refresh every 5 seconds and share production across
dashboard clients. The dashboard closes its display streams while its browser
tab is hidden and reconnects when visible. Trading continues on the server and
other clients remain independent. Open-trade actions wait for new trade and
balance snapshots after reconnecting; a confirmation opened before the tab was
hidden must be reviewed again if its trade or available funds changed. A retry
of an uncertain order keeps its existing operation ID.

If a trade or balance refresh fails, new DCA actions remain unavailable while
Moonwalker retries. Return to the tab with network access and check the
connection and exchange if the refreshing status persists.

Accumulation also uses `WS /accumulation/stream` for holding status and
`WS /accumulation/performance/stream` for Statistics. The latter shares
valuation snapshots and activity revisions so clients can refresh history
when it changes. See the [API reference](api.md#accumulation) for freshness
and recovery-only limitations.

## Backup And Restore

Backup and restore is available in Utilities:

- On first run, `Restore existing installation` is available on the opening
  entry screen.
- After the instance is configured, the same tools live in
  `Utilities -> Backup and restore`.

Two backup scopes are available:

- Config only: exports persisted configuration values only.
- Full backup: exports configuration plus trade-related data.

Full backups include:

- open trades
- closed trades
- unsellable trades
- trade/order history required by Moonwalker state
- per-deal execution replay history
- archived replay candles for closed-trade charts
- autopilot history
- uPNL history

Full backups do not include the shared ticker candle history table. On full
restore, Moonwalker clears current ticker history and fetches the required
history again for restored active trades. Closed-trade replay archives are
preserved separately, so replay charts for newly archived deals do not depend on
that shared ticker retention window. During startup backfill, Moonwalker also
repairs sparse closed-trade replay archives from bounded exchange OHLCV when the
exchange can supply the missing deal window, and otherwise keeps the existing
archive without blocking startup.

Completed and rejected exchange-placement records are portable audit history and
are included in full backups. Any placement that was unresolved when the backup
was created is kept separately in a SHA-256-checksummed recovery manifest. The
checksum detects accidental corruption; it does not authenticate a backup from
an untrusted source. For Dynamic DCA placements, on
restore, Moonwalker clears source exchange and client-order identities,
invalidates any nonportable result, retains the recorded capital reservation,
and marks the row `restored_quarantined`. Restored quarantined rows are never
submitted automatically. Keep trading paused and reconcile them manually before
resuming live operation.

Accumulation placements retain their recorded identities and evidence under
quarantine for explicit repair. See [accumulation backup and restore](accumulation.md#backup-and-restore).

Two restore modes are available:

- Restore config only: replaces configuration, leaves current trade data in
  place.
- Restore full backup: replaces both configuration and the included trade data.

Backups created before `4.9.0.0` may still carry the raw trade-mode bridge
keys (`trade_lifecycle_mode`, top-level `dynamic_dca`,
`sidestep_campaign_enabled`). Restoring such a backup is still supported: the
three keys are dropped silently and the rest of the backup restores normally,
because every legacy representation was equivalent to the default `trade_mode`
value (`dynamic_dca`). All other removed config keys are still rejected on
restore with a message that names the replacement key.

Restore requires explicit confirmation. Before replacing state, Moonwalker
blocks new exchange-order work and waits for already admitted order work to
finish. The restored instance remains paused in dry-run mode so the operator can
review configuration and trade state before deliberately activating and
resuming trading.

## Startup Recovery

Before any watcher or signal producer starts, Moonwalker reconciles every
nonterminal exchange-placement intent by stable client/exchange order identity.
If an intent cannot be resolved safely, startup fails closed and identifies the
operation requiring manual reconciliation. Capital recorded by an unresolved
buy remains reserved until the intent reaches a safe terminal state.

If only paused, quarantined accumulation obligations remain, startup can instead
serve restricted recovery access with trading workers stopped. See the
[accumulation recovery guide](howto-recover-accumulation.md#recover-after-restore-or-upgrade).

An accepted buy acknowledgement can omit fill details, especially for a capped
IOC safety order. Moonwalker records that acceptance and looks up the existing
order during startup; it does not submit another buy. Durable buy requests retain
the original safety-order percentage and strategy context, and later exchange
evidence retains local context from the earlier acknowledgement.

For a `local_recovery_failed` quarantine, keep the instance stopped and preserve
a database backup before any repair. Inspect the affected operation without
changing it:

```sql
SELECT operation_id, state, reason_code, exchange_order_id,
       request_json, result_json
FROM placement_intents
WHERE operation_id = '<operation-id-from-startup-log>';
```

Older requests may lack `so_percentage`. Recovery uses the original value from
the saved result when available. A base order can retain an unknown (`null`)
percentage, but a safety order with no original percentage remains blocked:
that value affects subsequent DCA progression and must not be guessed. If an
earlier failed reconciliation already erased the value, recover it from the
original order logs or a backup. Verify the exchange order's fills and local
execution ledger before an operator reopens that exact intent for reconciliation.
Quarantined rows are terminal and are not retried by restarting alone. Do not
delete the intent, mark it completed without persistence, or submit a replacement
buy to bypass the startup gate.

If Moonwalker fails during startup with a message like `SQLite corruption
detected in ...` or `SQLite index corruption detected in ...`, the local SQLite
database is damaged and Moonwalker will stop instead of continuing with unsafe
state.

Recommended recovery flow:

1. Run `sqlite3 <path-to-db> 'PRAGMA integrity_check;'`
2. If Moonwalker names a specific index, try `sqlite3 <path-to-db> 'REINDEX <index-name>; PRAGMA integrity_check;'`
3. If integrity check still reports errors, restore a known-good full backup or
   use SQLite recovery tooling before restarting Moonwalker
4. Start Moonwalker again only after the database file passes integrity checks

This corruption path is about the main Moonwalker database file, not the shared
ticker cache. Full backups already preserve replay archives and trade history
needed for recovery.

## Campaign residue recovery

The campaign-column removal migration rebuilds the trade tables without the
legacy campaign columns. Before it runs, startup verifies that no *open*
trade still references a campaign: if a row in `opentrades` carries a
non-null `campaign_id`, startup aborts with a message that names the affected
symbol(s). The migration is not run and the database is left unchanged.

This can only happen on an install that ran a pre-4.9 sidestep-era build with
an open position; every later release writes `campaign_id` as null.

Recommended recovery flow:

1. Note the affected symbol(s) from the startup log.
2. For each symbol, review the real open position on the exchange and confirm
   the local open-trade row matches it (amount, cost, open date).
3. Once the position is accounted for and the local row is its only record,
   stop Moonwalker and clear the residue:

   ```sql
   sqlite3 <path-to-db> \
     "UPDATE opentrades SET campaign_id = NULL WHERE campaign_id IS NOT NULL;"
   ```

4. Start Moonwalker again. The migration runs, the campaign columns are
   dropped, and the open trade keeps being managed by its `deal_id` (or the
   row's own identity when no deal id exists yet).

Historical (closed) trades are not gated: their campaign values are dropped
together with the column while all other trade data is preserved.

## Unsellable Trades

When a sell succeeds only partially, a proactive take-profit order cannot meet
the exchange minimum notional, or an active take-profit limit sell leaves a
remainder below that minimum, Moonwalker archives the remaining amount as an
unsellable trade instead of repeatedly retrying an exit the exchange cannot
accept. The active-limit path remains terminal even when its guarded market
fallback cannot sell below the configured TP price floor.

Important behavior:

- the sold portion is still recorded correctly in closed trades
- the unsellable remainder is moved out of active open trades
- unsellable trades no longer count against active open-trade slots
- the UI shows them in a dedicated `Unsellable` tab

Use the `Resolve` action after you have manually cleaned up the remainder on the
exchange side and want to remove it from the archive.

## Sell Protection

Moonwalker has two main protections against selling into short-lived spikes:

- TP spike confirmation can delay TP sells until the move remains valid long
  enough.
- Limit-sell market fallback uses a live-price floor guard before switching to a
  market sell.

This means a wick can still trigger evaluation, but Moonwalker tries to avoid
closing the trade at a worse price after the spike has already faded.

## Live Statistics

The dashboard statistics panel includes live runtime state beyond raw PnL:

- `Funds locked`: capital currently tied up in open deals
- `Funds available`: free quote balance when available from the exchange
- `Autopilot mode`: base Autopilot state (`low`, `medium`, `high`, or `none`)
- `Effective max bots`: the currently active max-deals limit after Autopilot and
  Green Phase are combined
- `Green phase` status: whether the market-speed monitor detected momentum and
  whether the guardrails allowed the temporary expansion

Green Phase can be detected but still blocked if reserve protection or locked
fund ceilings say there is not enough safe capacity left.

## Bybit authenticated request timestamps

Bybit and Bybit EU validate authenticated request timestamps within CCXT's
5,000 ms receive window. Moonwalker enables CCXT clock adjustment and explicitly
synchronizes time before each market metadata refresh. This ordering matters:
CCXT fetches authenticated currency metadata before the market fetch that would
normally perform automatic time synchronization.

If a market refresh receives `InvalidNonce`, Moonwalker synchronizes time and
retries that read once. A second rejection or a failed synchronization propagates
to the caller; stale metadata is not marked fresh. This retry does not replay
order submissions or widen the receive window.

Error `10002` can indicate clock drift or a request delayed in transit. Keep the
host clock synchronized with NTP. If rejections persist, check host clock status
(for example `timedatectl status` on systemd Linux) and latency to the exchange;
clock adjustment cannot make a request with excessive transit delay valid.

## Bybit EU recovery buy price bands

Capped recovery buys on `bybiteu` fetch the current spot price band through
CCXT's public `/v5/market/price-limit` endpoint before submission. Their IOC limit
is the lower of the strategy recovery ceiling and the exchange's maximum buy
price, rounded downward to a valid tick. Quantity, minimum notional and available
funds are checked using that effective limit. If the executable ask is above it,
Moonwalker skips the buy rather than exceeding either limit.

A malformed, mismatched or unavailable price band skips submission with
`exchange_price_band_unavailable`. Responses older than ten seconds or more than
five seconds ahead of the local clock are rejected; keep the host clock synchronized.
The price-band read has a ten-second timeout.

If Bybit EU explicitly rejects submission with code `170193` (maximum buy price
exceeded), Moonwalker refreshes the band and executable ask, repeats all buy
prechecks and retries at most once. The retry never increases the earlier limit.
Other errors, accepted unfilled IOC orders, and submissions with uncertain
acceptance do not trigger this retry; existing placement reconciliation applies.
This behavior affects capped Bybit EU recovery buys only. Binance and ordinary
market buys retain their existing paths. Strategy signals and recovery sizing
thresholds are unchanged.

## Bybit IOC acknowledgements and pending buys

A Bybit or Bybit EU capped recovery buy can return an acknowledgement before
its fill information is available. Moonwalker reads that same exchange order
up to three times, within five seconds, without placing another order. A terminal
positive fill, including a partially filled canceled IOC, is finalized using
the execution ledger. A confirmed canceled zero-fill order is released.

If the outcome remains unknown, the accepted placement stays blocked. On a later
buy attempt for that symbol, Moonwalker looks up the pending accepted operation
and resumes local persistence rather than submitting a duplicate. This read-only
recovery runs before admission for fresh capital, so a fully committed budget
does not block accounting for an existing order. Unavailable or
incomplete runtime lookups retain the block for a later attempt. Cancellation
during a lookup restores the accepted state and propagates cancellation. The recovery
lookup does not close the shared exchange client or replay the original buy. This recovery
is triggered by subsequent buy attempts, rather than a background polling job.

Existing accepted Bybit operations can recover on a subsequent signal after this
change is deployed. The actual exchange execution must be confirmed; removing an
accepted placement manually is not a substitute for accounting for its fills.
