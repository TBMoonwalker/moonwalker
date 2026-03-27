# Changelog

All notable changes to Moonwalker are documented in this file.

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
