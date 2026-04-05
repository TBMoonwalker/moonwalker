# Changelog

All notable changes to Moonwalker are documented in this file.

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
