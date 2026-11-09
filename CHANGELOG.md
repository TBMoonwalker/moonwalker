# Changelog

All notable changes to Moonwalker are documented in this file.

## [6.4.0.0] - Unreleased

### Breaking Changes

- Drop the 4.8.x-and-earlier (pre-4.9) trade-mode compatibility. Backups
  created before `4.9.0.0` that still carry the raw trade-mode bridge keys
  (`trade_lifecycle_mode`, top-level `dynamic_dca`,
  `sidestep_campaign_enabled`) are now refused on restore like any other
  removed config key, with a message that names the canonical `trade_mode`
  key, instead of being dropped silently. To restore such a backup, remove
  the three keys from its config rows first (every legacy representation was
  equivalent to the default `trade_mode` value, so nothing is lost). The
  pre-confirmation backup review no longer reports them as a silent drop: the
  `pre_4_9_bridge_keys` summary field and the `legacy_bridge_keys_dropped`
  finding are gone from `POST /config/backup/classify`, and the keys now
  surface as `removed_config_key` blocking findings.

### Added

- Pre-confirmation backup review: before restoring, the dashboard classifies
  the selected backup (read-only, no database access) and shows what the
  restore would do to it — the backup's era, the dropped legacy column values
  it silently discards, the placement intents that will restore into
  quarantine, and the config-only removal of the local accumulation pin.
  Backups the restore would refuse (campaign residue, removed config keys,
  incomplete accumulation sections, invalid recovery manifest) are flagged
  as blocking and their restore button is disabled;
  there is no force-restore path. Restore behavior itself is unchanged.
  See `POST /config/backup/classify` in the API reference.
- Operator repair path for quarantined classic-DCA placement intents: an
  instance whose startup gate is blocked by quarantined intents alone (no
  other nonterminal exchange work) now serves a restricted recovery mode
  instead of exiting with no operator access. The dashboard's Placement
  recovery card on the Trading overview lists every quarantined intent;
  **Repair** looks the order up on the exchange under the configured
  credentials and applies the confirmed terminal state locally (lookup-only —
  it never submits, cancels, or otherwise changes exchange state, and
  inconclusive evidence leaves the intent quarantined), and **Dismiss**
  records an explicit operator decision with a required note as a terminal
  disposition. Restart Moonwalker after every intent is resolved to clear the
  gate. New endpoints: `GET /orders/placement-recovery`, `POST
  /orders/placement-recovery/{operation_id}/repair`, `POST
  /orders/placement-recovery/{operation_id}/dismiss`.
- `docs/operations.md` "Startup Recovery" documents the placement recovery
  mode and the safe manual procedure for instances running an unfixed build.

### Changed

- Pruned the startup migration ledgers on the first startup after an
  installation reached the minimum supported version: applied ledger rows
  older than the floor are removed once (the floor marker and live
  migration records are kept, and installations below the floor keep their
  full history), and the near-duplicate dust-archive ledger entry (015, a
  no-op repeat of 003) is no longer tracked. Operator-invisible ledger
  hygiene; migration behavior for supported and pre-floor installations is
  unchanged.
- Split `service/orders.py`: classic-DCA trade finalization now lives in
  `service/dca/finalization.py`, the DCA execution lifecycle in
  `service/dca/order_lifecycle.py`, and the mode-neutral lifecycle routing in
  `service/order_routing.py`; `service/orders.py` is now a thin compatibility
  facade and `dca/engine.py` uses the lifecycle directly. Internal module
  move — no API, config, or schema change.

### Fixed

- Replay charts now show a muted "Indicator overlays unavailable for this
  trade." notice when no indicator series can be loaded — legacy rows without
  a deal id, empty indicator results, or failed indicator requests — instead
  of rendering candles with no explanation. Failed indicator requests are now
  reported to the browser console.
- Closed dynamic-DCA deals keep their strategy's indicator overlays on the
  replay chart after the deal closes: the active DCA strategy is now recorded
  on base orders that carry no strategy of their own when the order is
  created. Signal-triggered base orders previously recorded only the optional
  entry-filter strategy, so a deal that never placed a safety order lost its
  strategy metadata (and its overlays) the moment it closed. Deals already
  closed keep the unavailable notice.

## [6.3.0.0] - 2026-11-07

### Breaking Changes

- Raise the minimum supported version (MSV) to `6.3.0.0`. Installs below the
  floor still load and run (report-only), but their pre-floor data shapes are
  no longer supported: the first at-floor startup logs a one-time warning, and
  later startups report `supported`. Upgrade to `6.3.0.0` and export a fresh
  backup to move persisted data cleanly.
- Remove the CSV fee-provenance fallback. Trade rows created before the
  `cost_includes_fees` column (`5.3.0.0`) no longer have fee-inclusive cost
  inferred from the CSV plugin's generated order IDs; they are valued with the
  legacy fee estimate like any other unmarked row. Rows imported on or after
  `5.3.0.0` keep their explicit provenance.
- Remove the four-column accumulation CSV declaration format. Accumulation CSV
  entries now require the fee-aware columns
  (`date;symbol;price;amount;fee;fee_currency;amount_type`, with optional
  `fee_quote_value`). Four-column files and previously persisted four-column
  declarations are rejected with an explicit error; blank fee fields still mean
  unknown fees. The classic Dynamic DCA CSV import keeps its four-column
  format.
- Remove the `legacy_accumulation_graph` editor view for legacy-shape
  accumulation preset documents. Legacy documents remain fully readable by the
  accumulation runtime and the strategy catalog, but the strategy detail
  endpoint no longer renders them as an editable graph, and duplicating one is
  rejected.

### Changed

- The MSV floor marker is written on an existing install's first at-floor
  startup, so installs that skipped a floor release no longer keep reporting
  `unsupported` with guidance that can no longer be satisfied.

## [6.2.0.0] - 2026-11-05

### Fixed

- The Dynamic DCA statistics view now shows your full closed-trade history again. Closures from before the trading-lifecycle feature were left unclassified and disappeared from the DCA view and its totals. On the next startup the bot now marks each closure whose classic DCA mode is provable (it closed before accumulation existed on that database, or the database never ran accumulation) as classic DCA, and leaves unprovable closures unclassified rather than guessing.

## [6.1.0.0] - 2026-11-04

### Added

- `tp_floor_live_price_fallback` (off by default) for limit sell execution: when a take-profit limit sell times out, you can now opt in to completing the exit as a market sell as long as the live price still meets the TP floor. The bot re-checks the live price before sending the fallback and keeps the position open if the price has dropped back below the floor; a market order can never guarantee the floor.

### Changed

- The dashboard no longer refetches the full configuration on every menu click. Navigation now runs a lightweight freshness check and refetches only when another client has actually changed the settings, so moving between pages stays fast.
- The accumulation panel no longer refetches its page on quick route round trips. The loaded rows are kept, the live status stream is reconnected in place, and if the stream cannot deliver a snapshot within a few seconds the panel falls back to an ordinary refetch instead of going stale.
- The accumulation page now reflects activations retired while you were away. The retired holding comes off the page, and if it was the one you had selected, the panel re-binds to the first surviving activation so its detail and actions stay usable without extra clicks.
- The Overview profit chart repaints instantly when you return while the cache is fresh, and fetches fresh history when the cache has expired or a 15-minute data bucket boundary was crossed while you were away.
- Monitoring logs poll only while the panel is visible. Polling stops when the panel is hidden or paused and resumes when it comes back, so a cached panel no longer keeps requesting logs in the background.

### Fixed

- A take-profit exit that timed out on its limit sell could leave the position open with no visible way to resolve it. The timeout now reaches a deterministic outcome. The position is either kept open deliberately (default) or completed at market while the live price still meets the floor (opt-in via `tp_floor_live_price_fallback`).

## [6.0.0.0] - 2026-11-02

### Breaking Changes

- Remove historical campaign linkage from the trade database. A new schema
  migration rebuilds the trade tables without the dormant campaign columns
  (`campaign_id` on `trades`, `closedtrades`, `tradeexecutions`,
  `placement_intents`, and `opentrades`, plus the seven unused sidestep-era
  waiting-state columns on `opentrades`) and drops their indexes. Historical
  closed trades keep their full trade data, but the campaign they once
  belonged to is no longer stored or shown, and dashboard row identity falls
  back to `deal_id` (then the row id). The rebuild keeps every other column
  and row, preserves indexes and user triggers that reference only kept
  columns, keeps row-id sequences and accumulation references intact, and
  runs each table atomically, so a failed or interrupted rebuild leaves the
  database exactly as it was.
- Startup aborts with an action message when an open trade still carries a
  non-null `campaign_id` residue. The migration does not run until the
  residue is reviewed and cleared. See "Campaign residue recovery" in
  `docs/operations.md` for the documented flow.
- Full backup restores are refused under the same condition: restoring a
  backup whose open-trade rows still reference a legacy campaign would
  silently drop that linkage, so the restore aborts before writing anything
  and names the affected symbols and the recovery procedure.
- This release supports installations at schema baseline 4.9.0.0 or newer.
  A startup preflight compares the database's last-known baseline against
  the minimum supported version; a database below the floor is reported as
  unsupported, with upgrade guidance, but the preflight never blocks
  startup.

### Added

- `GET /monitoring/msv` reports the database's baseline against the minimum
  supported version, so dashboards can show whether the installation sits
  inside the supported window.

### Changed

- `/config` and `/settings` now serve the dashboard app, which redirects
  them to the control center; unknown top-level paths go to the trades view.
  The server no longer rejects these paths outright.
- Writing a removed config key from the UI or API no longer errors: the
  value is stored but never read by the runtime. Backup restores still
  reject most removed keys with a message that names the replacement key.
- Closed-trade replay no longer falls back to the currently configured
  strategies for executions recorded without strategy metadata; those
  historical executions no longer receive a fallback indicator overlay.

### Removed

- The legacy trade-mode bridge keys (`trade_lifecycle_mode`, top-level
  `dynamic_dca`, `sidestep_campaign_enabled`) are no longer migrated or
  handled at startup. Restoring a pre-4.9 backup that still carries them
  drops the three keys silently, because every legacy representation was
  equivalent to the default `trade_mode` value (`dynamic_dca`), so no
  setting is lost.
  The other removed config keys (for example `autopilot_max_fund`) are still
  rejected on restore with a message that names the replacement key.
- Restores no longer rewrite legacy `trade_mode` values (such as
  `sidestep`) to the current default. If a restored backup carries an
  out-of-contract value, the bot will not start signals until you correct
  the `trade_mode` setting; the runtime fails closed with a message that
  names the key.

## [5.5.1.0] - 2026-10-31

### Added
- Show a connection sync indicator in the dashboard header. A small badge next
  to the app title tells you whether the dashboard is live, reconnecting, or
  showing stale data; a one-line status bar underneath makes the same state
  visible on narrow screens. When the WebSocket drops, the indicator warns you
  before you act on stale trades.

### Fixed
- Correct the OHLCV timestamp serializer for far-future tz-aware values. The
  serializer was reusing the binary `TZif` shipped with the OS, whose
  transition tables stop at ~2037 and fall back to the last known offset for
  any later instant. The fix re-resolves tz-aware timestamps through the stdlib
  `zoneinfo` database, so a 12:00 Vienna wall-clock in 2040 (CEST, +02:00) now
  serializes to 10:00 UTC instead of 11:00.

### Changed
- Trim the logging infrastructure. Six module-level loggers that were imported
  but never used have been removed; six module groups that each opened their
  own `RotatingFileHandler` on the same file in the same process are now
  unified to a single handler per domain, so log records stop interleaving and
  file rotation stays in lockstep.
- Fold the accumulation domain's logging into one file. Execution, runtime,
  notification, and performance-stream log records all write to
  `logs/accumulation.log` instead of three scattered files. Operators now
  watch a single stream for accumulation activity.
- Route accumulation notification and performance-stream log records through
  the project `LoggerFactory` instead of the bare `logging` module, so the
  failures land in their domain file instead of leaking into `run.log`.

## [5.5.0.2] - 2026-10-31

### Fixed
- Tolerate a sub-lot rounding difference between the exchange-reported free balance
  and the DB-stored accumulated quantity in the accumulation owned-base check. Bybit
  and Bybit-EU report a spot balance at a fixed decimal precision while the ledger
  keeps a higher-precision total from the fill reports, so a fraction-of-a-quantum
  shortfall (for example a half-satoshi, a few hundredths of one percent of what is
  held) is now treated as a reporting artifact instead of parking the step as
  "owned base missing or encumbered." A genuine encumbrance — an order hold, a pending
  fill, an external transfer, or any shortfall that is not sub-lot — still trips the
  guard, because the tolerance is capped at the smaller of one trading quantum and one
  percent of the owned quantity.

## [5.5.0.1] - 2026-10-31

### Fixed
- Resolve an accumulation rebase park on Bybit and Bybit-EU where the owned-base
  check read the wrong wallet: the auto-detected balance read can return the spot
  wallet while your base sits in the Unified Trading Account, so a step parked as
  "owned base missing or encumbered." The check now reconciles against the unified
  wallet when it holds the base, and falls back to the previous read for every
  other account.
- Name the free, owned and deficit magnitudes when an accumulation owned-base check
  fails, so a parked symbol reads as a self-diagnosing symptom instead of an opaque
  error type.

## [5.5.0.0] - 2026-10-30

### Added
- Reconnect to a live profit and open-trades view that refreshes from a fresh,
  uncached snapshot instead of a possibly-stale cached one, so a recovery client
  or a dashboard that just came back to the foreground never shows stale numbers.
- Freshness-aware trade actions: selling, resizing or closing a trade re-checks
  that the underlying data and your available funds are unchanged since the dialog
  opened, and asks you to review the action again when they have moved.

### Changed
- Split the profit and open-trades streams into an ordinary on-cadence update and
  an on-demand recovery update, so a slow refresh no longer stalls the dashboard's
  regular updates.

### Fixed
- Name the failing condition when an accumulation step trips an internal check, so
  the failure log tells you which invariant broke instead of only the error type;
  exchange and timeout failures still log no request payload.

## [5.4.1.0] - 2026-10-28

### Added
- Follow accumulated coins, purchase costs and recorded order activity in a
  dedicated statistics view that updates live.
- See the conditions an accumulation strategy is waiting for, including its
  current indicator values and candle-close requirements.

### Changed
- Tailor configuration, statistics and navigation to the active trading mode,
  and protect configuration changes from conflicting dashboard edits.

### Fixed
- Keep accumulation statistics responsive and reduce temporary memory use
  when the recorded order history grows.
- Stop a DCA trade at its latest tracked market price instead of deleting its
  trade history. The remaining coins are valued at the current price as a
  separately recorded market valuation, without a sell order or fee. Actual
  partial-sale records remain in the execution history; realized profit is
  unavailable when their fees cannot be verified.
  A fill that lands while the take-profit order is being canceled is included,
  and a missing or invalid price keeps the open trade.

## [5.4.0.0] - 2026-10-26

### Changed
- DCA and accumulation keep their trade-specific buy, sell and dust handling
  separate while using the same exchange execution and recovery infrastructure.

### Fixed
- Import a single purchase from pasted or uploaded CSV text, including fee
  columns, without it being mistaken for a file path. CSV URLs and file sources
  remain supported.

## [5.3.0.0] - 2026-10-26

### Added
- Accumulate spot holdings without automatic profit-taking. Start with an ASAP
  base order or import an existing CSV purchase, then manage pause, resume,
  additional orders and sales from the open-trade card. See the
  [accumulation guide](docs/accumulation.md).
- Build and backtest accumulation strategies in the existing Strategy Builder
  and Backtest views, using shared indicators and the exchange candle timeframe
  when the strategy inherits it.
- Follow the next buy condition, current-cycle orders, recorded fees and
  performance through the existing trade status, history and portfolio views.

### Changed
- DCA and accumulation share exchange submission, execution recovery, history
  preparation and capital admission. Uncertain orders remain blocked pending
  reconciliation, and mode changes retain ownership of unresolved activity.
- Accumulation buys respond to new declines with spacing anchored to the base
  order. Candle-close waits show indicative conditions without promising a buy.
- macOS startup and CI discover supported Homebrew Python and Node installations.
  Redis remains running when an instance stops so other installations can use it.
- Updated reviewed backend and frontend dependencies, including compatible major
  versions, and documented upgrade and recovery procedures.

### Fixed
- Preserve exact accounting through partial fills, manual sales, unsellable dust
  transfers and fresh accumulation cycles after a holding closes.
- Count declared CSV acquisition fees once in DCA valuation, preserve their
  provenance across backups, and distinguish imported purchases from later fills.
- Keep accumulation entry recovery, order logging, registration pagination and
  WebSocket database access consistent across restarts and multiple dashboards.
- Show the first performance sample and release chart subscriptions when their
  views close.
- Address dependency security advisories, including the verified Zod release,
  certificate trust and redirect handling updates.

### Removed
- Retired accumulation dip presets and duplicate utility, strategy-selection and
  portfolio panels; accumulation uses the existing trading and configuration views.

## [5.2.5.0] - 2026-10-13

### Fixed
- Exchange connections use CCXT's patched multidict dependency, resolving the
  known vulnerability while preserving the exchange library's required versions.

### Changed
- Updated compatible backend and frontend dependencies, including VueUse 15,
  Vitest 5 and filelock 4. Recovery status retains its five-second refresh cadence
  and releases scheduled work when the card closes.

## [5.2.4.0] - 2026-10-13

### Fixed
- Recovery safety-order status now explains when TP is already within the
  configured rebound target, instead of replacing that reason with a missing
  or unchanged strategy signal. The status updates when a further price drop
  makes another buy useful; trading rules remain unchanged.

## [5.2.3.0] - 2026-10-11

### Fixed
- Bybit and Bybit EU recovery buys now resolve accepted IOC acknowledgements
  through the existing order, account for canceled partial fills, and recover
  pending buys without duplicate submissions. Recovery remains available when
  the capital budget is fully committed or an order lookup is interrupted.

## [5.2.2.0] - 2026-10-11

### Fixed
- Bybit and Bybit EU market refreshes now synchronize request timestamps before
  authenticated metadata reads and recover from one timestamp rejection without
  restarting the signal plugin. Repeated failures still propagate; order
  submissions are never replayed by this recovery.

## [5.2.1.0] - 2026-10-11

### Fixed
- Bybit EU recovery safety orders now respect the exchange's current maximum buy
  price, preventing avoidable price-band rejections. A changing price band permits
  one checked retry; unavailable limits and uncertain submissions never bypass
  the strategy price ceiling or existing order protections.

## [5.2.0.0] - 2026-10-10

### Fixed
- Cap‑priced recovery buys now truncate toward the maximum buy price instead of
  rounding up, so a recovery fill can no longer land above the limit you set. A
  cap below the exchange's smallest price tick is rejected with a clear reason
  instead of being placed as a bad order, and a rejected or fill‑zero capped buy
  is reported as "not filled" and retried rather than being miscounted as a
  completed buy.

### Changed
- Chart and uPNL visuals now share a single framing style, which removes the
  duplicated per‑component chart layout CSS and keeps the two charts aligned.
- Frontend startup now relies on Vite's automatic code splitting to keep the
  router's lazy views lazy — a production‑build regression test blocks any chart
  module from the startup bundle and holds it under a 250 KB gzip budget, so the
  old manual split groups that could pull charted code back into startup are no
  longer used.
- Browser storage access is centralized in one fault‑tolerant helper. A read or
  write against a blocked, private‑mode, or full storage now falls back to the
  in‑memory value instead of throwing, and callers can inject a storage source
  for testing.
- Configuration hot‑reload is now owned by the application lifecycle as a
  reconnecting, supervised listener: it resynchronizes after each reconnect so no
  change can fall between the snapshot and the subscription, resubscription
  failures back off, and an unexpected listener fault is reported to supervision
  instead of failing silently.

### Added
- Vulture dead‑code scanning is pinned as an on‑demand development check (a
  conservative `pyproject.toml` scan plus a broader size‑ordered review). It is
  not yet a CI gate while the remaining candidates are being reviewed.

### Removed
- Legacy, now‑unused backend helpers and frontend type declarations were
  removed, including superseded closed‑trade persistence paths, unused
  indicator lookups and guardrail visitors, and unreferenced TypeScript exports.
- The `vitest.config.ts` configuration was renamed to `vitest.config.mts`, and
  end‑to‑end specs are no longer swept into the unit‑test configuration.

## [5.1.1.0] - 2026-10-08

### Fixed
- Accepted buys can now recover after restart without losing their original
  safety-order percentage or strategy context when exchange lookup supplies
  fresh fill data. Recovery never submits a replacement buy. Older safety-order
  records whose percentage is unavailable remain blocked with a clear repair
  message; see [startup recovery](docs/operations.md#startup-recovery).

## [5.1.0.0] - 2026-10-07

### Added
- The capital-settings section now shows a live exposure estimate as you tune
  it. It adds the draft base order, the safety-order reserve a new deal would
  hold, and the safety orders still open across your current deals, then
  applies your buffer, so you can see whether a new deal will fit before
  saving.

### Changed
- AI-trust calibration settings now live in their own configuration section
  instead of being mixed in with the general and advanced settings.

### Fixed
- Paged trade feeds no longer let a page you navigated to while it was still
  loading overwrite the rows currently on screen. A stale in-flight response
  is now discarded instead of clobbering a newer view.

### Removed
- Pathfinder closed-trade feedback for the WebSocket signal plugin is removed.
  The outbound feedback posts, the saved delivery receipts, and the "Trade
  Feedback" entry in Monitoring are gone, and closing a deal no longer runs
  the old feedback worker or writes feedback rows. Saved signal settings still
  load unchanged — the retired feedback option is simply ignored. Closed-trade
  statistics keep using the same execution fees as before.

## [5.0.2.0] - 2026-09-29

### Fixed
- The Closed trades title now shows the full trade count instead of the ten rows
  loaded on the current page.

## [5.0.1.0] - 2026-09-29

### Fixed
- Open trade charts now show the active DCA strategy indicators alongside entry
  indicators, including before the first safety order. Historical closed-trade
  charts continue to show the strategies recorded for those trades.

## [5.0.0.0] - 2026-09-29

### Added
- Pause and resume live trading now sit in the persistent top bar on every page.
    Pausing blocks new entries and re-entries while existing exits keep running,
    and a pause or resume triggers the same cross-tab configuration
    invalidation as a save so open dashboards react at once.
- A section-navigation rail in the Control Center jumps to the advanced
    configuration you need instead of scrolling past every section.
- A capital-budget portfolio-exposure readout (with tests) reports locked,
    reserved, and tradable amounts as percentages of the configured budget,
    with an over-budget flag.

### Changed
- The console adopts a calmer charcoal design language with selective green
    accents. Typography and surface tokens move to a neutral base so data and
    status read as the priority over chrome.
- Configuration is the first thing you see: the Control Center now opens on a
    setup-first workspace. Setup opens by section, Advanced is grouped by domain
    for expert tuning, and a ready dry-run instance ends Setup with a guarded
    live activation review.
- Autopilot on/off moves to Advanced → Autopilot, and backup/restore and the
    Telegram test move to Utilities.
- The per-section live preview panels (overview, autopilot, monitoring,
    owner-confidence) are removed to cut duplicated UI; those surfaces live in
    their own views. The budget bar and sidebar status were simplified to read
    at a glance.
- On phones, desktop-only navigation hides itself so the layout fits a narrow
    screen instead of overflowing.

### Fixed
- Portfolio exposure now scales to the configured capital budget instead of a
    raw figure, so it reads correctly against how much you are actually
    invested.

## [4.15.0.0] - 2026-09-27

### Added
- The expanded open-trade card now shows a live Recovery DCA status panel with the
    distance to the next trigger, the ATR-based spacing, and a buy / projected
    take-profit estimate for the price last evaluated. It refreshes at least every
    30 seconds while recovery evaluation runs, collapses to "Updating status" after
    90 seconds without a fresh evaluation, and explains how the numbers are
    calculated in a "How this is calculated" disclosure.
- "Trade Feedback" is now selectable in Monitoring so you can inspect feedback
    delivery from one view: delivery becoming enabled or paused, skipped
    provenance or provider checks, acknowledgements, retry attempts, and permanent
    rejections, all with safe error codes.

### Changed
- Recovery detail moved out of the order timeline into its own reusable panel, so
    the status and its explanation read on their own instead of only inside the
    expanded trade row.

### Fixed
- Closing a deal that leaves unsellable dust now records its final outcome to the
    Pathfinder feedback outbox in the same operation that closes the trade, using
    the full entry cost and the actual sell proceeds; the unsold remainder
    contributes nothing. Previously a dust-close could silently skip feedback.

## [4.14.0.0] - 2026-09-27

### Added
- Delisting protection now lives in the Exchange settings and adapts to the
   exchange you trade on. Binance uses an isolated production schedule client
   (with optional dedicated read-only credentials); Bybit and Bybit EU follow
   the public delisting announcement feed and fall back to the exchange's own
   market status if that feed is briefly unavailable; exchanges without a
   supported schedule show no delisting control at all.
- When a Bybit feed blip leaves the schedule unverified, Bybit stays fail-open:
   new buys trade off the exchange market status rather than freezing, and open
   trades are not spammed with an "all buys blocked" alert. Binance still fails
   closed.

### Fixed
- The Bybit announcement date parser now rejects far-future years, matching the
   cap already applied to timestamped entries, so a malformed announcement can no
   longer mint a delisting event that freezes new buys on a matched spot market.
   Existing exits keep running throughout.

### Changed
- The four delisting configuration keys moved from Signal settings to Exchange
   settings so they travel with the exchange they belong to.
- UI wording that assumed Binance now refers to "the exchange," so the trade
   screen and alerts read correctly on any supported exchange.

## [4.13.0.0] - 2026-09-26

### Added
- Optional Pathfinder closed-trade feedback for the WebSocket signal plugin.
  Enable the feedback switch to report final net outcomes for live and demo
  trades, including DCA buys and partial exits. Feedback defaults off.
- Durable feedback receipts retry temporary delivery failures after restarts.
  Disabling feedback pauses delivery; changing providers cannot send an old
  trade to the new provider. Incomplete fee accounting blocks submission.

### Fixed
- Account for CCXT's multiple-fee representation and fallback order fees when
  deducting base-asset buy fees, so inventory and feedback use the same fees.

## [4.12.1.0] - 2026-09-26

### Fixed
- The pair-age filter no longer wrongly rejects established pairs. Some
   exchanges return candles newest-first, so a cached listing date could be the
   most recent candle, making an old pair look freshly listed and be held out of
   the bot. The gate now rechecks a recent cached date against a bounded history
   window, treats an old candle as proof of sufficient age, and corrects a stale
   cached date with an upsert, so eligible pairs are admitted and their signals
   stop being dropped.

### Changed
- When a signal is ignored because a pair's age can't be verified, the bot
   now logs the symbol and the `pair_age` threshold instead of dropping it
   silently.

## [4.12.0.0] - 2026-09-26

### Added
- A client-side stale-while-revalidate cache for the uPNL timeline and the
   per-period profit history. After a page reload the charts paint instantly
   from the cache and reconcile in the background, so the "overall" and profit
   views no longer blank out or spin on first open. A guarded `localStorage`
   helper backs it, so blocked or full storage never breaks the dashboard.

### Changed
- Switching between the profit tabs (Overall / Daily / Monthly / Yearly) keeps
   each chart mounted through naive-ui's per-pane `display-directive`, so a
   switch is a pure show/hide: no ECharts re-animation and no refetch. This
   removes the "timecap" that made a tab change feel like a fresh load, and a
   switch now costs no network request.

### Removed
- No removals in this release.

## [4.11.0.0] - 2026-09-25

### Added
- Theme control: choose light, dark, or "auto" (follow the operating system)
   from the header. The choice is remembered across reloads, and a chosen theme
   is applied before the first paint, so the dashboard no longer flashes the
   wrong colors when it loads.

### Changed
- Every control-center surface, panel, and status wash now recollors from the
   chosen theme instead of the operating system, so light and dark read the same
   everywhere: mission copy, the strategy canvas and library, the setup, progress,
   and restore panels, and the heatmap's empty cells.
- The control-center mode tabs now expose full keyboard and screen-reader
   behavior (arrow keys, Home and End, and tab / panel roles), and the backtest
   screen's status chip now colors through the same theme as the rest of the app.

### Fixed
- The admission strip's "open" chip no longer fails the 4.5:1 text-contrast
   check in either theme; its text now picks a color that reads in both
   (14.06:1 on light, 12.13:1 on dark) while warning and error chips keep
   their own colors.
- Muted secondary text that was hard to read is made darker to clear the
   WCAG-A contrast threshold.
- Pagination controls on the Open, Closed, and Unsellable trade feeds now meet
   the 44px touch-target minimum on phones, matching the rest of the app.

### Removed
- No removals in this release.

## [4.10.0.0] - 2026-09-22

### Removed
- The unrouted config view chain (`views/ConfigView.vue`,
   `components/Config.vue`, `components/config/ConfigGeneralSection.vue`) is
   deleted. After the `/config` route was retired in favor of the control
   center, these three files were unreachable from the app and the router;
   the shared section components still used by the control center are kept.
   Five path-anchored regression tests are repointed onto the live
   control-center surfaces that provide the same coverage.
- The unused `OpenTrades.__dict__` method (it returned an f-string and had no
   callers) and the orphaned `idx_opentrades_lifecycle_mode` index, which no
   query filters on, are dropped. `exposure_state` and
   `idx_opentrades_exposure_state_symbol` are retained: they back the
   open-trades read path and `LifecycleSnapshotIdentity`.

## [4.9.0.0] - 2026-09-21

### Added
- Add a per-open-trade "Deny from new entries" row action. Clicking it appends
  the trade's base token to `pair_denylist` so the symbol is blocked from
  opening new signal deals while its existing open trade runs to its natural end.
- Render a "Denylisted" tag on open-trade rows whose base token is present in
   `pair_denylist`, driven by the live config snapshot.
- Add `POST /config/denylist/deny`, a server-side endpoint that reads the current
   `pair_denylist`, de-duplicates the base token, and writes the whole list back
  atomically under a new global `Config` write lock so concurrent dashboard
  clients cannot clobber each other's denylist appends.
- Add `Config.append_denylist_token` / `Config.merge_denylist_tokens` and the
   module helpers `parse_denylist_tokens`, `to_base_token`, and
   `serialize_denylist_tokens` in `service/config.py`, plus the frontend
   `parseDenylistTokens` / `isSymbolDenied` helpers.
- Add regression coverage for token normalization, de-duplication, concurrent
   appends (no lost update), future-entry gating, leaving open trades untouched,
   full-list replacement, and the denylist deny endpoint.

## [4.8.0.0] - 2026-09-20

### Removed
- Sidestep mode is gone. `dynamic_dca` is now the only trade mode; the
  `spot_campaigns` table model, `SpotSidestepCampaignService`, the 7
  `sidestep_*` config keys, the `waitingCampaigns` websocket, and the
  `/trades/waiting` REST endpoints and stream are all removed. Legacy config
  keys (`trade_lifecycle_mode`, `dynamic_dca`, `sidestep_campaign_enabled`)
  migrate on load to the canonical `trade_mode = "dynamic_dca"`. On-disk
  campaign columns stay dormant. The "Waiting Campaigns" UI tab and its
  replay surface are removed from the trades page.
- The `sidestep_exit` close reason and the `TRADE_MODE_SIDESTEP` /
  `is_sidestep_mode` / waiting-campaign lifecycle machinery are removed from both
  the backend and the frontend.

### Changed
- `trade_mode`, `tradeLifecycle`, and the readiness / config-payload paths now
  canonicalize to `dynamic_dca` only; `normalizeTradeMode` and the
  `isDynamicTradeMode` / `isDynamicDcaMode` helpers always resolve to
  `dynamic_dca`.
- Coverage floors were re-ratcheted after the branch removal:
   `backend/controller/config.py` to 64.0 and `backend/service/ai_trust.py` to
  71.0 in `scripts/check_coverage_thresholds.py`.
- `docs/api.md`, `docs/configuration.md`, and `docs/operations.md` no longer
  document the removed sidestep / waiting-campaign surface.

## [4.7.1.1] - 2026-09-16

### Fixed
- The per-symbol stream watchdog now caps a hung-feed stale window at one configured candle interval, so a frozen daily or weekly feed is reclaimed within a day instead of waiting 72h to 21d for the timeout to elapse.
- A single symbol whose `watch_ohlcv`/`watch_trades` coroutine hangs is now detected even while the other symbols keep trading, recovering that feed without leaving stale candles in the DCA and signal path.
- The strategy-builder mode no longer spins at 100% CPU: a Vue `:ref` function callback re-fires on every parent re-render, which re-triggered the Rete graph render in a loop. `bindReteHost` is now idempotent, so only a genuine host change schedules a render.

### Changed
- Bumped ccxt to 4.5.78, ta-lib to 0.8.0, websockets to 17, and refreshed the security and dev tooling floors (Python and JavaScript lockfiles).

## [4.7.1.0] - 2026-09-15

### Added
- A liveness watchdog that detects a frozen ccxt-pro websocket stream and
  recovers it after 1800s of silence by reloading the exchange client and
  respawning the stream.
- Regression coverage for the stream watchdog and its reclaim path
  (`backend/tests/test_watcher_stream_watchdog.py`).

### Changed
- Bounded the indicator result caches to `TTLCache(maxsize=4096, ttl=600s)` to
  stop unbounded growth; symbols dropped from the watch list are unwatched during
  task sync.
- Anchored log output to `<repo>/backend/logs` (`MOONWALKER_LOG_DIR` override) so
  launching from a foreign CWD no longer creates stray `logs/` directories.
- Retired the no-op `general.debug` config key, superseded by the
  `MOONWALKER_LOG_LEVEL` / `MOONWALKER_DEBUG` environment variables.
- Moved the `timezone` setting from the General section to the Exchange section,
  where it belongs with the API fields it governs.
- Hid the now-empty General section from the setup wizard (advanced-only), making
  Exchange the first setup step.

## [4.7.0.0] - 2026-09-13

### Added
- A frontend-staging guard so a missing built SPA surfaces loudly instead of as a
  bare 500: `run.sh start` now hard-fails fast when assets do not stage, the SPA
  controller raises an actionable `HTTPException`, and startup logs the gap.
- `PRODUCT.md` capturing the product record and a design-audit report for the
  Control Center view.

### Changed
- Canonicalized the design system in `DESIGN.md` against the open DESIGN.md
  format.
- The control-center view and its components received design-audit fixes and
  reduced-motion handling.
- Switched the Python formatter from Black to Ruff (`ruff format --check`
  in CI, pinned `ruff==0.15.22` in `requirements-dev`); the backend was
  reformatted and project config (`pyproject.toml`, `opencode.json`) now
  targets Ruff with 88-col, double-quote, LF settings.

## [4.6.3.0] - 2026-09-04

### Added

- Added optional sidestep guards that confirm exit and re-entry signals on closed
  candles, prevent re-entry above a configured premium over the sidestep exit,
  and protect timed-out sidestep sell fallbacks from excessive slippage.

### Changed

- Added sidestep controls for fresh-long confirmation, spike-safe re-entry, and
  sell fallback protection, with matching runtime validation and regression tests.

## [4.6.2.0] - 2026-09-03

### Fixed

- Stop retrying a take-profit limit remainder that is below an exchange's
  minimum order value. It is now recorded as unsellable, including the minimum
  and estimated values needed for manual resolution.

## [4.6.1.0] - 2026-09-02

### Fixed

- Stop retrying proactive take-profit exits when an exchange rejects the
  remaining token amount as below its minimum order value. The remainder is now
  recorded as unsellable so it is visible for manual resolution.

## [4.6.0.0] - 2026-07-28

### Added

- Added durable placement intents, client operation IDs, startup reconciliation,
  and crash-recovery workflows so accepted exchange orders cannot be blindly
  retried after a local failure.
- Added schema-migration records, verified backup/restore handling, canonical
  execution ledgers, and archived replay candles for reliable trade-history
  reconstruction.
- Added versioned Strategy Builder graphs with validation, conflict detection,
  reusable catalog/IR seams, and desktop editing plus mobile review workflows.
- Added AI trust calibration, persisted analytics, work-queue coordination, and
  CoinMarketCap-backed ranking support behind explicit runtime controls.

### Changed

- Split DCA decisions, lifecycle snapshots/mutations, persistence records,
  runtime services, and sell fallback orchestration into focused typed modules.
- Supervised application services through the Litestar lifespan and made
  startup/shutdown cleanup best-effort across all owned resources.
- Refined the Control Center, statistics, monitoring, replay, and trade-ledger
  surfaces for clearer responsive behavior and multi-client-safe mutations.
- Expanded regression coverage and coverage ratchets across DCA decisions,
  durable placement, crash recovery, migrations, Strategy Builder, responsive
  interactions, and typed order results.

### Fixed

- Waiting campaign TradingView replays now resolve the persisted sidestep
  campaign execution timeline so the strategy indicators used by prior legs
  render even when the current flat Waiting deal has no executions.
- Prevented limit-sell cancel/fill races from submitting a duplicate market
  fallback; fallback now requires explicit canceled state and finite,
  non-negative quantities that reconcile with the submitted amount.
- Kept capped IOC buys pending when exchange fill evidence is missing,
  non-numeric, non-finite, negative, or contradictory instead of treating
  ambiguous responses as definitive zero fills.
- Prevented same-symbol buy/sell action conflicts, repeated manual operation
  IDs, malformed accepted-order responses, and post-submission enrichment
  failures from causing unsafe retries.
- Serialized Strategy Builder rendering and debounced, canceled, and
  generation-guarded validation so stale async results cannot overwrite the
  current graph.
- Corrected mobile trade expansion columns and stale table widths so DCA
  execution details and statistics remain readable without horizontal overflow.

## [4.3.0.1] - 2026-07-27

### Changed

- Documented Waiting campaign replay behavior, keyboard expansion, legacy
  history fallbacks, live stream, and action endpoints across the README,
  configuration, API, and operations guides.
- Updated compatible Python and frontend packages after vulnerability,
  provenance, and compatibility review, and regenerated the integrity-pinned
  dependency locks.

### Security

- Removed the temporary `PYSEC-2026-3447` audit exception after CCXT 4.5.68
  adopted setuptools 83.0.0; Python and npm audits now pass without ignored
  vulnerabilities.

## [4.3.0.0] - 2026-07-27

### Added

- Waiting sidestep trades now open the same TradingView replay chart used by
  open and closed trades, including buy, re-entry, safety-order, and exit
  markers.
- Waiting replay rows can be expanded by pointer or keyboard and remain useful
  for legacy campaigns with sparse execution history by falling back to
  campaign timestamps and the recorded waiting exit price.

### Fixed

- Mobile Waiting and Unresolved actions now keep readable, aligned controls
  instead of clipping their Activate, Stop, More, or Resolve labels.
- Waiting replay execution markers now stay chronological for both ISO and
  legacy numeric timestamps, and malformed or unavailable execution history
  falls back safely without hiding the chart.

## [4.2.0.0] - 2026-07-26

### Added

- Added bounded recovery-target DCA sizing with ATR-aware safety-order spacing,
  configurable recovery budgets, projected take-profit context, shadow mode,
  and operator-facing diagnostics.
- Added optional exchange delisting protection for new base orders, safety
  orders, and sidestep re-entry while preserving exits for existing positions
  and surfacing prominent open-trade warnings.
- Added a WebSocket signal source with reconnect handling, keepalive
  acknowledgement, admission controls, GUI configuration, and runtime health
  reporting.
- Added local AI Trust observation, calibration, entry-sizing guidance,
  analytics, persisted prediction history, and an operator cockpit.
- Added proactive take-profit limit pre-arming and spike confirmation controls
  to reduce missed wick exits without selling below the configured profit floor.
- Added strict Python and npm dependency locks, artifact-integrity checks,
  vulnerability audits, registry-signature verification, and documented Node 24
  startup guidance.

### Changed

- Refined the Control Center and trade/statistics surfaces for clearer setup,
  responsive operation, accessible controls, stable navigation, and shared
  configuration freshness across multiple dashboard clients.
- Aligned backend and frontend configuration contracts, readiness validation,
  backup restore behavior, and WebSocket signal requirements.
- Updated supported runtime packages and development tooling after advisory,
  provenance, signature, and compatibility review.

### Fixed

- Prevented take-profit fallback paths from placing an exit below the configured
  profit floor.
- Prevented signal admission reservations from leaking when watcher preparation
  or entry sizing fails.
- Prevented stale AI outcome recovery, provider retry, post-fill persistence,
  startup cleanup, SQLite integrity, cache invalidation, and hidden Control
  Center lifecycle failures from obscuring runtime state.
- Corrected dynamic DCA deal-cap, delisting, configuration migration, and
  responsive trade-ledger edge cases found during QA.

### Security

- Enforced trusted private, loopback, or explicitly allowed Host authorities on
  every HTTP and WebSocket request, plus same-origin and dashboard-header checks
  for browser mutations.
- Redacted all WebSocket credential headers and sensitive subscription payloads
  from public configuration responses.
- Made backup restore explicitly confirmed, serialized, paused, dry-run safe,
  cache coherent, and mutually exclusive with complete DCA/order execution.
- Made Python dependency-lock validation fail closed on direct URLs, VCS/local
  sources, installer directives, and injected continuation lines.

## [4.1.0.0] - 2026-06-08

### Added

- Open and closed trade replay charts now show the strategy indicator overlays
  that explain the trade, including EMA, Bollinger Band, RSI, MACD, and
  bandwidth series in price and indicator panes.
- Backtest charts now share the same TradingView indicator rendering helpers, so
  strategy overlays stay consistent across simulated and replayed trades.
- Strategy runtime startup health checks now log explicit per-symbol evaluation
  signals, making stale or unavailable strategy history easier to diagnose.
- Regression coverage now protects replay indicator warmup windows, chart
  overlay rendering, strategy runtime health checks, and watcher startup probes.

### Fixed

- Long-window replay indicators now load enough pre-window history before
  trimming to the visible chart range, so EMA100/EMA200 and related overlays do
  not disappear from trade replay charts.
- Trade replay expand controls are now labelled buttons for assistive
  technologies instead of cursor-only table cells.
## [4.0.4.1] - 2026-06-05

### Added

- Additional regression test coverage for StatisticsView edge cases: empty sorter
  objects, watch-based page correction on data shrink, and columnSortOrder function
  behavior with null/undefined state.
- Verified design baseline to DESIGN.md with live-measured fonts, colors, performance
  metrics, and known deviations tracked for future remediation.

### Changed

- Extract named constants (DEFAULT_SORT_STATE, DEFAULT_PAGINATION, SYMBOL_PAGE_SIZE)
  in test files to improve maintainability and eliminate duplicated literals.

## [4.0.4.0] - 2026-06-05

### Fixed

- Clicking pagination numbers on the Statistics page now correctly updates the
  symbol table data instead of showing the same first-page results.
- Clicking a sort column header on the Statistics page no longer reduces the
  visible rows; the table now shows the full page of sorted results.
- All sortable columns (Trades, Win Rate, Total Profit, Avg Profit) now
  display the correct sort indicator arrow on the active column only.

### Added

- Regression test coverage for Statistics pagination, column sorting, data
  formatting, and sort indicator behavior.

## [4.0.3.0] - 2026-06-03

### Fixed

- Keep upgraded sidestep installations in `trade_mode = sidestep` when legacy
  3.3-era trade-mode rows are still present, so the Control Center no longer
  falls back to dynamic DCA setup after a 4.0 upgrade.
- Add regression coverage that proves the legacy sidestep bridge is runtime-only:
  removed compatibility keys stay hidden, and Moonwalker does not write a new
  `trade_mode` row while loading the upgraded config.

## [4.0.2.0] - 2026-06-02

### Fixed

- Restore closed-trade replay charts for high-precision trades so rows such as
  `VIRTUAL/USDC` render candles instead of an empty dark chart frame.
- Keep the closed-trade replay timeline and chart in stable desktop columns,
  while preserving the stacked mobile layout.
- Add regression coverage for replay chart precision, layout-ready painting,
  explicit empty and error states, and exact sell marker placement.

## [4.0.1.0] - 2026-06-01

### Fixed

- Make the Sidestep waiting tab readable on mobile by replacing the squeezed
  desktop trade table with a compact waiting-campaign card layout.
- Add regression coverage that keeps the mobile waiting-campaign layout on its
  dedicated summary column instead of falling back to the full desktop table.

## [4.0.0.0] - 2026-05-31

### Breaking Changes

- Remove old-version upgrade bridges. This release removed legacy Strategy
  Builder custom graph shapes, old EMA strategy state tables, old campaign
  close-row percentage repairs, and the `ema_swing_reverse` compatibility
  alias. The legacy trade-mode config keys (`trade_lifecycle_mode`,
  `dynamic_dca`, `sidestep_campaign_enabled`) were not removed in this
  release: the trade-mode bridge did not exist yet, and the configuration
  migration that canonicalized it kept running until it was removed in the
  unreleased entry above.
- Remove legacy Autopilot and Backtest shims:
  `autopilot_entry_stretch_max_multiplier` is no longer read as a fallback for
  `autopilot_base_order_stretch_max_multiplier`, and direct `Backtest(...)`
  callers may no longer pass `step_scale`.
- This version intentionally breaks direct upgrades from old releases that
  still depend on those bridges. Upgrade through `3.3.0.0` first, save the
  current configuration, and export a fresh backup before installing this
  version.

### Removed

- Delete obsolete EMA strategy-state models and Strategy Builder legacy
  migration code so the runtime only supports the current graph IR and canonical
  config keys.

### Changed

- Tighten the Statistics trade activity panel so sparse closed-trade heatmaps
  use the space for compact activity metrics instead of leaving a large empty
  surface.
- Improve Strategy Builder graph readability with larger node typography,
  wider nodes, and a less aggressive default graph fit.
- Calm the open-trade row action area so Sell and More remain readable without
  dominating the trading table.

### Fixed

- Restore direct navigation to the Statistics route and Strategy Builder route
  so browser refreshes and deep links land on the intended workspace.
- Render the Strategy Builder graph after async strategy loading by waiting for
  the canvas host before initializing Rete.
- Keep the mobile app wordmark and Strategy Builder action buttons contained on
  narrow screens.

## [3.3.0.0] - 2026-05-28

### Added

- Add the operator-facing Backtest workspace with strategy replay controls,
  weekly candles, dynamic DCA and sidestep modes, chart indicators, base and
  safety-order markers, trade tables with timestamps, previous-run comparison,
  and backend-safe error states.
- Add backend backtest APIs, isolated strategy replay state, causal indicator
  evaluation, shared DCA math, shared analytics summaries, OHLCV range caps,
  pagination pacing, and regression coverage for runtime, engine, API, fetch,
  analytics, and DCA behavior.
- Add Bollinger Bands, RSI, and MACD indicator support plus the Bollinger Buy
  strategy using wick-based Bollinger/EMA context checks.
- Add average lines to the daily, monthly, and yearly profit charts.

### Changed

- Align backtest configuration with current Moonwalker trading behavior by
  calculating DCA step scaling dynamically and leaving stop loss disabled when
  empty.
- Rework backtest symbol selection, form spacing, chart markers, and statistic
  cards to match the trading and statistics surfaces.
- Upgrade safe frontend and backend dependencies, including the Litestar route
  annotation update required by the current backend startup path.
- Harden `run.sh` so startup installs backend requirements, verifies
  dependency compatibility, validates controller imports, and cleans stale lock
  files when the backend exits immediately.

### Removed

- Remove the Bollinger Sell strategy from sell-strategy selection while keeping
  Bollinger Buy available for buy setups.

## [3.2.0.0] - 2026-05-21

### Added

- Visual Strategy Builder in the Control Center: drag-and-drop node editor
  to compose, validate, and save custom trading strategies from indicator,
  logic, state, and value nodes.
- Strategy Runtime engine that executes IR-based strategies with full signal
  lifecycle: pre-check, build, evaluate, and post-check hooks, including
  required history lookback enforcement.
- Strategy capability service to detect available strategies, missing indicators,
  and unsupported node types at build time.
- Built-in strategy library with 5 pre-built strategies (EMA down, EMA low
  rebound, EMA swing, EMA20 swing, EMA20 swing reverse) available as
  read-only templates that can be duplicated into custom strategies.

### Changed

- Convert all strategy implementations from Python modules to JSON IR
  (Intermediate Representation) consumed by the Strategy Runtime engine.
- Centralize strategy validation into a single service with node-level,
  connection-level, and graph-level checks.
- Add strategy schema versioning for forward-compatible IR evolution.

### Fixed

- Strategy Builder reactivity: setting a decision node now re-renders the
  graph and provides visual feedback.
- Delete confirmation dialog now uses the app-native Naive UI dialog
  instead of browser's native confirm.

## [3.1.0.0] - 2026-05-17

### Added

- Statistics dashboard for closed-trade performance analysis with KPI cards,
  trade activity heatmap, per-symbol breakdown, duration extremes, drawdown
  risk metrics, and profit distribution histogram.

### Changed

- Extract datetime and duration parsing helpers from autopilot_memory into a
  shared helper module for reuse across analytics and autopilot services.

### Fixed

- Eliminate redundant secondary database query in analytics summary calculation.
- Broaden duration parsing regex to support trades longer than 99 hours.

## [3.0.0.1] - 2026-05-16

### Changed

- Make `trade_mode` the canonical operator-facing trade lifecycle setting, with
  `dynamic_dca` and `sidestep` as the only supported dashboard modes.
- Keep `trade_lifecycle_mode`, `dynamic_dca`, and
  `sidestep_campaign_enabled` as one-bridge-release compatibility mirrors while
  the backend and frontend normalize around `trade_mode`.
- Block live trade-mode switches when open trades or waiting sidestep campaigns
  still exist, and surface the same structured migration or restore errors in
  the Control Center restore review flow.

### Fixed

- Preserve inactive mode settings across trade-mode switches, saves, reloads,
  and restores so switching away from sidestep or dynamic DCA does not erase
  the hidden configuration for the other mode.
- Remove stale `Trade lifecycle` terminology from Control Center setup copy and
  top-level docs so operators see the shipped `trade_mode` language
  consistently.

## [3.0.0.0] - 2026-05-13

### Changed

- Remove static DCA code, consolidate around `trade_mode` (`dynamic_dca` and `sidestep`).
- Update documentation to reflect new trade-mode model.

## [2.0.0.0] - 2026-05-12

### Changed

- Implement spot shorting strategy with dedicated campaign support.
- Optimize code and clean up architecture.

## [1.4.0.2] - 2026-05-06

### Changed

- Fix live mode activation logic.
- Clean up code smells and remove leftover legacy code.

## [1.4.0.1] - 2026-05-05

### Fixed

- Size partial sell retries from remaining position.

## [1.4.0.0] - 2026-04-28

### Breaking Changes

- Remove the one-release `autopilot_max_fund` compatibility alias. Moonwalker now accepts only `capital_max_fund` for the global capital limit.
- Reject config writes and backup restores that still reference `autopilot_max_fund`, so pre-cutover clients and backups must be updated before they can be used with this version.

### Changed

- Stop exposing `autopilot_max_fund` in backend config snapshots, frontend config load or submit flows, Control Center key routing, and Green Phase or capital-budget runtime resolution.
- Filter removed config keys out of newly exported backups so new-version backups stay restoreable without carrying forward dead config rows.
- Rework the Control Center overview lower section into one shared operator workspace so Configuration, Autopilot, and Monitoring read as related subsections instead of a stack of equal nested cards.

### Fixed

- Tighten backend and frontend regression coverage around removed-key snapshot filtering, config update rejection, backup export or restore behavior, and canonical capital-limit usage across Autopilot and Green Phase.

## [1.3.0.0] - 2026-04-25

### Added

- Add a global capital budget authority so every live buy path is checked against the protected capital limit before exchange execution, even when Autopilot is disabled.
- Add Capital Budget controls to setup and advanced configuration, with one-release compatibility for existing `autopilot_max_fund` installs.
- Show real tradable funds in the dashboard by combining exchange free balance with remaining global budget headroom.

### Changed

- Let Autopilot optionally stretch the effective capital limit from realized closed-trade profit, with wider entry and safety-order ranges only inside that earned-profit envelope.
- Reserve estimated future safety-order budget for open deals so new entries do not consume capital that existing DCA plans may still need.
- Route Green Phase and Autopilot threshold calculations through the global capital limit instead of the old Autopilot-scoped max-fund setting.

### Fixed

- Return manual buy failures back to the caller when the shared budget or exchange preflight blocks the order, so the API no longer reports success for a skipped buy.
- Tighten backend and frontend regression coverage around capital leases, configured budget persistence, manual buy blocking, legacy alias loading, profit stretch, and dashboard tradable funds.

## [1.2.0.0] - 2026-04-22

### Added

- Add a persisted Autopilot memory service, `/autopilot/memory` API, trust board cockpit, and Control Center overview previews so operators can see favored and cooling symbols, recent smart plays, and whether trust-driven entry sizing is active.
- Add ranked scarce-bot admission that uses symbol trust to choose which candidates get the last free bot slots, with one shared resolver and reservation handling across ASAP and SymSignals.
- Add guarded per-symbol entry sizing on top of the suggested base order, including baseline fallback logic and configuration/UI surfaces for enabling it deliberately.

### Changed

- Rework the Control Center overview around a calmer mission panel, owner-confidence summary, and dedicated Autopilot, Monitoring, and Config preview cards, with direct navigation into the new Autopilot workspace.
- Surface Autopilot memory hints in the statistics dashboard and expand backend/frontend regression coverage around symbol trust, admission, entry sizing, routing, and Control Center presentation.

### Fixed

- Keep scarce-bot admission honest by tightening max-bot usage, releasing reservations on failed buy paths, and sharing the same ranked decision seam across both signal plugins.
- Repair Control Center and Autopilot UI regressions found during design and QA, including broken overview mounting, cramped status copy, wrapping and layout glitches, and missing keyboard/focus affordances on interactive surfaces.

## [1.1.7.0] - 2026-04-09

### Changed

- Move closed-trade replay archive repair off the blocking startup path so Moonwalker can finish booting promptly even on older instances with lots of closed deals to inspect.

### Fixed

- Keep replay archive backfill limited to the background runtime path and reserve exchange-based repair for already-archived sparse deals, so legacy trades without archives no longer trigger a per-deal startup crawl.
- Add backend regression coverage for the non-blocking replay backfill startup path, the background scheduling hook, and the archive-missing exchange-repair guard.

## [1.1.6.0] - 2026-04-09

### Fixed

- Repair sparse closed-trade replay archives by rebuilding the deal window from bounded exchange OHLCV when local replay data only contains boundary candles, so long-running trades stop collapsing down to just the start and end candle after restart.
- Keep that sparse-archive repair path best-effort by falling back to the existing archive when the exchange history fetch is unavailable, so startup backfill does not fail just because repair data could not be fetched at that moment.
- Tighten bounded exchange-history paging so replay archive repair stops exactly at the requested end timestamp instead of carrying extra candles past the deal window.
- Add backend regression coverage for sparse replay archive repair and bounded exchange history fetches, so the replay backfill path keeps the full trade window instead of silently regressing to edge-only candles.

## [1.1.5.0] - 2026-04-09

### Changed

- Keep closed-trade replay markers and candles aligned with the real final sell by pairing exact-price sell markers with a dedicated chart overlay series and by letting replay archive backfill repair stale archived tails.
- Restore the brighter bullish green on open and closed trade buy markers so replay arrows match the chart's existing bullish candle language again.

### Fixed

- Include the close-time in-memory candle when a trade archives into closed-trade replay, so new closes keep the candle where the sell actually happened.
- Repair already-archived replay deals when startup backfill finds a newer persisted sell-time candle than the archived tail, so previously broken closed trades can self-heal on restart.
- Add regression coverage for live close-time candle archiving, incomplete archive repair, exact sell marker placement, and replay buy-marker color consistency.

## [1.1.4.0] - 2026-04-08

### Changed

- Stabilize the backend cleanup program across config, data, watcher, DCA, and exchange paths so each runtime responsibility has a clearer home instead of living in one oversized service file.
- Share config update request parsing and validation between the single-key and multi-key controller paths, and isolate OHLCV payload assembly, watcher queue behavior, DCA TP and safety-order state, and exchange order lookup into dedicated backend helpers.

### Fixed

- Lock config update conflicts, OHLCV payload assembly, and database init sequencing behind direct regressions so backend cleanup stops depending on “it probably still works.”
- Preserve watcher backpressure and DCA handoff behavior under queue coalescing and overflow, so runtime refactors do not quietly change trading semantics.
- Add direct regression coverage for exchange trade reconciliation fallback, DCA TP confirmation and trailing state, watcher queue delivery, and the extracted backend seam boundaries.
- Normalize mixed closed-trade timestamp formats in profit aggregation so the Daily, Monthly, and Yearly profit tabs stop throwing 500s when legacy ISO rows and newer space-separated rows coexist.

## [1.1.3.0] - 2026-04-08

### Changed

- Turn Control Center into a real composition surface by extracting setup, advanced, overview, mission, lifecycle, navigation, feedback, and workspace seams out of the old monolithic view.
- Share config-editor defaults, assembly, and backup or restore presentation across Control Center and the standalone config surface so the same workflow stops living in multiple places.

### Fixed

- Remove the expired `/settings` and `/config` Control Center entry seams so `/control-center` is the single supported configuration route across the frontend router, backend SPA fallback, and operator docs.
- Normalize text-backed SQLite timestamp handling across history reads, replay archives, housekeeping, and latest-ticker lookups so short numeric timestamps and millisecond timestamps behave consistently.
- Prevent Control Center from throwing a setup-time `ReferenceError` by deferring submit callbacks until workspace actions are initialized.
- Add regression coverage for the extracted Control Center seams, canonical Control Center routing, replay archive bounds, and SQLite timestamp normalization helpers.

## [1.1.2.0] - 2026-04-05

### Changed

- Turn index-only SQLite startup corruption into a concrete recovery path by naming the damaged index and pointing operators to `REINDEX` before a full restore.
- Document the same `REINDEX`-first recovery flow in operations guidance so the startup error and manual runbook stay aligned.

### Fixed

- Add regression coverage for index-only SQLite corruption so startup diagnosis keeps distinguishing between rebuildable index damage and broader database corruption.

## [1.1.1.0] - 2026-04-05

### Fixed

- Detect SQLite corruption during startup and fail with an actionable message that points operators to `PRAGMA integrity_check` and backup or recovery steps.
- Add regression coverage for malformed SQLite startup failures so the corruption path stays explicit.

## [1.1.0.0] - 2026-04-05

### Added

- Review closed trades with the same expandable replay chart language as Open Trades, including buy markers, a final sell marker, and an execution timeline.
- Persist per-deal execution rows and archived replay candles so newly closed deals keep their replay history through housekeeping, backup, restore, and safe history deletion.

### Changed

- Bound closed-trade replay reads to the actual trade lifecycle window so old deals stop showing candles far beyond the entry and exit.
- Keep legacy closed rows expandable so they explain when replay history is unavailable instead of failing silently.
- Relax the frontend `npm-run-all` pin to accept compatible `4.1.5` installs.

### Fixed

- Normalize closed-trade replay fallback payloads before rendering so legacy rows do not break when OHLCV endpoints return an empty object.
- Normalize ticker-housekeeping timestamp handling so second-based and millisecond-based candle rows follow the same retention rules.

## [1.0.3.0] - 2026-03-27

### Added

- Add explicit Control Center config-trust states and browser-local invalidation fanout so saves, restores, and live activation can refresh other tabs safely.
- Add regression and coverage tests for SPA deep-link fallbacks, config freshness timestamps, and config invalidation send and receive paths.

### Changed

- Surface config trust directly in the Control Center mission panel so clean tabs can auto-refresh quietly while draft tabs get a clear reload decision.

### Fixed

- Serve hashed Vite bundles directly from `/assets` and restore SPA deep links for `/control-center`, `/config`, `/monitoring`, and `/settings`.
- Keep `/config/all` snapshots tied to their own persisted `config_updated_at` instead of stamping stale payloads with a newer freshness marker.

## [1.0.2.0] - 2026-03-22

### Added

- Persist EMA swing lows by symbol and timeframe so restart recovery can continue higher-low tracking safely.
- Add direct regression coverage for Control Center setup-entry history state and EMA swing recovery edge cases.

### Changed

- Reconstruct the latest qualifying EMA swing low from recent candle history when persisted restart state is missing.

### Fixed

- Preserve first-run Control Center setup-entry choices in browser history so Back and Forward stay inside the setup flow instead of dropping to a blank page.

## [1.0.1.0] - 2026-03-21

### Changed

- Let the expanded open-trade chart use the full card surface while preserving rounded clipping.
- Make selected tabs and primary actions read clearly active across Control Center, Monitoring, Utilities, and Trades.
- Give the trades tab row the same line-style active treatment as the profit tabs.
