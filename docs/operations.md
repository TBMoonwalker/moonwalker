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
- backend pytest suite
- frontend type-check (`vue-tsc`)
- frontend tests (`node --test`)
- frontend production build (`vite build`)

## Runtime Model

Moonwalker runs as a single-node, single-instance application.

- one instance owns its own DB, config, watcher state, and trading engine
- multiple dashboard clients can connect to the same instance concurrently
- websocket streams are shared fan-out producers, not one producer per client

`./run.sh start` builds the frontend, copies the assets into the backend,
creates or reuses `.venv`, installs backend requirements, and starts the
Litestar app in the background.

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

These websocket streams refresh every 5 seconds and broadcast shared payloads
to all connected dashboard clients.

## Backup And Restore

Backup and restore is available directly from the Configuration page.

Two backup scopes are available:

- Config only: exports persisted configuration values only.
- Full backup: exports configuration plus trade-related data.

Full backups include:

- open trades
- closed trades
- unsellable trades
- trade/order history required by Moonwalker state
- autopilot history
- uPNL history

Full backups do not include ticker candle history. On full restore, Moonwalker
clears current ticker history and fetches the required history again for
restored active trades.

Two restore modes are available:

- Restore config only: replaces configuration, leaves current trade data in
  place.
- Restore full backup: replaces both configuration and the included trade data.

## Unsellable Trades

When a sell succeeds only partially and the leftover amount falls below the
exchange minimum notional or similar constraints, Moonwalker archives the
remainder as an unsellable trade.

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
