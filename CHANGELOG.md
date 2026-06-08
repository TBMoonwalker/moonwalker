# Changelog

All notable changes to Moonwalker are documented in this file.

## [Unreleased]

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

- Remove old-version upgrade bridges. Moonwalker no longer migrates legacy
  trade-mode config keys (`trade_lifecycle_mode`, `dynamic_dca`,
  `sidestep_campaign_enabled`), legacy Strategy Builder custom graph shapes,
  old EMA strategy state tables, old campaign close-row percentage repairs, or
  the `ema_swing_reverse` compatibility alias.
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
