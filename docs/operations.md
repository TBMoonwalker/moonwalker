# Operations

## CI / Tests
Run the full backend and frontend verification suite:
```bash
cd scripts && ./ci.sh
```

Current CI checks include:
- backend format (`black --check`)
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
- `WS /trades/waiting`
- `WS /statistic/profit`

Main REST statistics endpoint:
- `GET /statistic/profit-overall/timeline`

These websocket streams refresh every 5 seconds and broadcast shared payloads
to all connected dashboard clients.

## Waiting Campaign Replay

Waiting sidestep campaigns use the same TradingView replay language as open and
closed trades. In the Trades page, select **Waiting** and expand a campaign row
with a pointer, Enter, or Space. Nested action controls do not toggle the row.

Moonwalker loads the persisted campaign's chronological execution history
before mounting the chart, renders the strategy indicators used by its legs,
and marks buys, re-entries, safety orders, and exits. This campaign context
keeps indicators available while the current flat Waiting deal has no
executions. If a legacy campaign has sparse, malformed, or temporarily
unavailable execution history, the chart still opens using the campaign
timestamps and recorded waiting exit price. Replay expansion is read-only and
does not activate, stop, pause, or resume a campaign.

## Backup And Restore

Backup and restore lives in the Control Center:

- On first run, `Restore existing installation` is available on the opening
  entry screen.
- After the instance is configured, the same tools live in
  `Control Center -> Utilities -> Backup and restore`.

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
an untrusted source. On
restore, Moonwalker clears its source exchange and client-order identities,
invalidates any nonportable result, retains the recorded capital reservation,
and marks the row `restored_quarantined`. Restored quarantined rows are never
submitted automatically. Keep trading paused and reconcile them manually before
resuming live operation.

Two restore modes are available:

- Restore config only: replaces configuration, leaves current trade data in
  place.
- Restore full backup: replaces both configuration and the included trade data.

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

## Unsellable Trades

When a sell succeeds only partially, or a proactive take-profit order cannot
meet the exchange minimum notional, Moonwalker archives the remaining amount as
an unsellable trade instead of repeatedly retrying an exit the exchange cannot
accept.

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
